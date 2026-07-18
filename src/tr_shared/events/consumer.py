"""Unified Redis Stream event consumer.

Retry + crash-recovery use Redis Streams' native PEL:
- A failed handler is **not** acked — the entry stays in the consumer group's
  Pending Entry List (PEL).
- ``_claimer_loop`` runs ``XAUTOCLAIM`` on a fixed idle floor and reclaims any
  entry idle past it — **regardless of owner** — so both retry-failures and
  crash-orphans (entries a since-dead consumer read but never acked) are
  recovered by one mechanism, and re-processed inline from the claim return.
- After ``max_retries`` attempts an entry is moved to the DLQ and acked.

One stream entry per logical event: no XADD-to-source retry storm.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Protocol

import redis.asyncio as redis

from tr_shared.events.dead_letter import DeadLetterHandler
from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.retry_policy import RetryPolicy
from tr_shared.events.retry_state import RetryStateStore

logger = logging.getLogger(__name__)

EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class IdempotencyChecker(Protocol):
    async def is_processed(self, event_id: str) -> bool: ...

    async def mark_processed(self, event_id: str) -> None: ...


class InMemoryIdempotencyChecker:
    """In-memory dedup with optional Redis fallback for cross-instance checks."""

    def __init__(self, redis_client: redis.Redis | None = None, group_name: str = "", ttl_days: int = 7) -> None:
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._redis = redis_client
        self._group = group_name
        self._ttl = ttl_days * 86400

    async def is_processed(self, event_id: str) -> bool:
        if event_id in self._ids:
            return True
        if self._redis:
            key = f"{self._group}:processed:{event_id}"
            return bool(await self._redis.exists(key))
        return False

    async def mark_processed(self, event_id: str) -> None:
        self._ids[event_id] = None
        if len(self._ids) > 10_000:
            # FIFO eviction: oldest 5000 entries
            for _ in range(5_000):
                try:
                    self._ids.popitem(last=False)
                except KeyError:
                    break
        if self._redis:
            key = f"{self._group}:processed:{event_id}"
            await self._redis.setex(key, self._ttl, "1")


class EventConsumer:
    """Unified Redis Stream consumer.

    Features:
    - Handler registration (exact match and ``prefix.*`` wildcard).
    - PEL-based retry via ``XAUTOCLAIM`` with a fixed idle floor.
    - Crash-orphan recovery: idle pending entries owned by dead consumers are
      reclaimed and re-processed.
    - Startup sweep of empty idle zombie consumers (``XGROUP DELCONSUMER``).
    - Dead-letter queue for malformed or exhausted messages.
    - Pluggable ``IdempotencyChecker`` for deduplication.
    - Supports both flat-field and payload-wrapped message formats.
    """

    def __init__(
        self,
        redis_url: str,
        stream_name: str = "tr_event_bus",
        consumer_group: str = "default_group",
        consumer_name: str = "worker_1",
        batch_size: int = 10,
        block_ms: int = 5000,
        retry_policy: RetryPolicy | None = None,
        idempotency_checker: IdempotencyChecker | None = None,
        parse_mode: str = "flat",
        claim_min_idle_ms: int = 30_000,
        claimer_poll_interval: float = 5.0,
        claim_count: int = 1000,
        zombie_idle_ms: int = 86_400_000,
    ) -> None:
        self._redis_url = redis_url
        self._stream_name = stream_name
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._retry_policy = retry_policy or RetryPolicy(max_retries=0)
        self._idempotency: IdempotencyChecker | None = idempotency_checker
        self._parse_mode = parse_mode
        self._claim_min_idle_ms = claim_min_idle_ms
        self._claimer_poll_interval = claimer_poll_interval
        self._claim_count = claim_count
        self._zombie_idle_ms = zombie_idle_ms

        self._redis: redis.Redis | None = None
        self._handlers: dict[str, EventHandler] = {}
        self._running = False
        self._dlq: DeadLetterHandler | None = None
        self._retry_state: RetryStateStore | None = None
        self._claimer_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
        self._dlq = DeadLetterHandler(self._redis, self._stream_name, self._consumer_group)
        self._retry_state = RetryStateStore(self._redis, self._stream_name, self._consumer_group)
        await self._ensure_consumer_group()
        await self._sweep_zombie_consumers()

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def _ensure_consumer_group(self) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.xgroup_create(self._stream_name, self._consumer_group, id="0", mkstream=True)
            logger.info("Created consumer group '%s' on '%s'", self._consumer_group, self._stream_name)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _sweep_zombie_consumers(self) -> None:
        """Delete consumers with no pending entries that have been idle past the
        threshold. Restarts churn consumer names (hostname-pid), so empty dead
        consumers accumulate forever otherwise. Never removes a consumer that
        still holds pending entries — the claimer drains those first."""
        if self._redis is None:
            return
        try:
            consumers = await self._redis.xinfo_consumers(self._stream_name, self._consumer_group)
        except redis.ResponseError:
            return
        for consumer in consumers:
            name = consumer.get("name")
            if not name or name == self._consumer_name:
                continue
            if int(consumer.get("pending", 0)) == 0 and int(consumer.get("idle", 0)) > self._zombie_idle_ms:
                try:
                    await self._redis.xgroup_delconsumer(self._stream_name, self._consumer_group, name)
                    logger.info("Swept idle empty consumer '%s' from group '%s'", name, self._consumer_group)
                except redis.ResponseError:
                    logger.warning("Failed to sweep consumer '%s' — continuing", name)

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type] = handler

    def handler(self, event_type: str) -> Callable[[EventHandler], EventHandler]:
        def decorator(func: EventHandler) -> EventHandler:
            self.register_handler(event_type, func)
            return func
        return decorator

    def _resolve_handler(self, event_type: str) -> EventHandler | None:
        h = self._handlers.get(event_type)
        if h:
            return h
        for pattern, h in self._handlers.items():
            if pattern.endswith(".*") and event_type.startswith(pattern[:-2]):
                return h
        return None

    def _parse(self, message_id: str, data: dict[str, str]) -> EventEnvelope | None:
        try:
            if self._parse_mode == "payload":
                return EventEnvelope.from_payload_wrapper(message_id, data)
            return EventEnvelope.from_flat(message_id, data)
        except Exception:
            logger.exception("Failed to parse message %s", message_id)
            return None

    async def _process_message(self, message_id: str, data: dict[str, str]) -> tuple[bool, bool]:
        """Process one message. Returns ``(handler_ok, should_ack)``.

        A failed handler returns ``(False, False)`` — the caller skips XACK so
        the entry stays in the PEL for the claimer to retry. Terminal outcomes
        (success, malformed, duplicate, no-handler, retries-exhausted) return
        ``should_ack=True``.
        """
        envelope = self._parse(message_id, data)
        if envelope is None:
            if self._dlq:
                try:
                    await self._dlq.move(message_id, data, "Malformed message")
                except Exception:
                    logger.exception("DLQ move failed for malformed message %s — continuing", message_id)
            else:
                logger.error(
                    "Malformed message discarded — no DLQ configured",
                    extra={"message_id": message_id, "stream": self._stream_name},
                )
            return True, True

        if self._idempotency and await self._idempotency.is_processed(envelope.event_id):
            logger.debug("Skipping duplicate event: %s", envelope.event_id)
            return True, True

        handler = self._resolve_handler(envelope.event_type)
        if handler is None:
            logger.warning(
                "No handler registered for event type — event discarded",
                extra={
                    "event_type": envelope.event_type,
                    "event_id": envelope.event_id,
                    "stream": self._stream_name,
                },
            )
            return True, True

        try:
            await handler(envelope)
        except Exception as exc:
            return await self._handle_failure(message_id, data, envelope, exc)

        if self._idempotency:
            await self._idempotency.mark_processed(envelope.event_id)
        if self._retry_state:
            await self._retry_state.clear(message_id)
        logger.info("Processed event %s (%s)", envelope.event_id, envelope.event_type)
        return True, True

    async def _handle_failure(
        self, message_id: str, data: dict[str, str], envelope: EventEnvelope, exc: Exception
    ) -> tuple[bool, bool]:
        """Record the failed attempt. Below ``max_retries`` → leave in PEL for
        the claimer. At/above → DLQ + ack. A retry-state Redis failure is
        fail-safe: route straight to the DLQ."""
        try:
            attempts = await self._retry_state.increment(message_id) if self._retry_state else 1
        except Exception:
            logger.exception("Retry-state increment failed for %s — routing to DLQ", message_id)
            attempts = self._retry_policy.max_retries

        logger.warning(
            "Handler failed for event %s (attempt %d/%d)",
            envelope.event_id, attempts, self._retry_policy.max_retries, exc_info=exc,
        )
        if attempts >= self._retry_policy.max_retries:
            if self._dlq:
                try:
                    await self._dlq.move(message_id, data, f"Max retries exceeded: {exc!s}")
                except Exception:
                    logger.exception("DLQ move failed for %s — continuing", message_id)
            if self._retry_state:
                await self._retry_state.clear(message_id)
            return False, True
        return False, False

    async def _ack(self, message_id: str) -> None:
        if self._redis:
            await self._redis.xack(self._stream_name, self._consumer_group, message_id)

    async def start(self) -> None:
        await self.connect()
        self._running = True
        self._claimer_task = asyncio.create_task(self._claimer_loop())

        logger.info("Consumer started: %s on %s", self._consumer_name, self._stream_name)
        try:
            await self._consume_loop()
        finally:
            self._running = False
            if self._claimer_task:
                self._claimer_task.cancel()
                try:
                    await self._claimer_task
                except asyncio.CancelledError:
                    pass
            await self.disconnect()

    async def _consume_loop(self) -> None:
        if self._redis is None:
            return
        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=self._consumer_group,
                    consumername=self._consumer_name,
                    streams={self._stream_name: ">"},
                    count=self._batch_size,
                    block=self._block_ms,
                )
                if not messages:
                    continue
                for _stream, stream_msgs in messages:
                    for msg_id, msg_data in stream_msgs:
                        _ok, should_ack = await self._process_message(msg_id, msg_data)
                        if should_ack:
                            await self._ack(msg_id)
            except redis.TimeoutError:
                # Idle blocking-read timeout: no messages within block_ms. redis-py
                # 8.x raises TimeoutError where 7.x returned empty — both mean
                # "nothing to read, poll again". Caught before ConnectionError
                # because some redis-py versions subclass it there.
                continue
            except redis.ConnectionError:
                logger.exception("Redis connection error")
                try:
                    await self.disconnect()
                    await self.connect()
                except Exception:
                    logger.exception("Reconnect failed")
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in consumer loop")
                await asyncio.sleep(1)

    async def _claim_once(self) -> int:
        """One ``XAUTOCLAIM`` pass over the group PEL. Reclaims entries idle past
        ``claim_min_idle_ms`` — regardless of owner — and processes them inline,
        so failed retries and crash-orphans from dead consumers are recovered
        together. Returns the number of entries processed.

        A single call (up to ``_claim_count`` entries) rather than a cursor loop:
        ``XCLAIM`` resets an entry's idle timer to 0 on claim, so re-scanning
        within one pass would re-claim the same still-failing entries forever.
        Any remainder beyond ``_claim_count`` is picked up on the next poll. The
        fixed idle floor is the retry backoff; ``max_retries`` bounds attempts.
        """
        if self._redis is None:
            return 0
        _cursor, claimed, _deleted = await self._redis.xautoclaim(
            name=self._stream_name,
            groupname=self._consumer_group,
            consumername=self._consumer_name,
            min_idle_time=self._claim_min_idle_ms,
            start_id="0-0",
            count=self._claim_count,
        )
        for msg_id, msg_data in claimed:
            _ok, should_ack = await self._process_message(msg_id, msg_data)
            if should_ack:
                await self._ack(msg_id)
        return len(claimed)

    async def _claimer_loop(self) -> None:
        while self._running:
            try:
                await self._claim_once()
                await asyncio.sleep(self._claimer_poll_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in claimer loop")
                await asyncio.sleep(self._claimer_poll_interval)

    async def stop(self) -> None:
        self._running = False
        await self.disconnect()

    @property
    def is_running(self) -> bool:
        return self._running
