"""Unified Redis Stream event consumer with retry, DLQ, delayed requeue, and wildcard handlers."""

import asyncio
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Protocol

import redis.asyncio as redis

from tr_shared.events.dead_letter import DeadLetterHandler
from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.retry_policy import RetryPolicy

logger = logging.getLogger(__name__)

EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class IdempotencyChecker(Protocol):
    """Protocol for pluggable deduplication."""

    async def is_processed(self, event_id: str) -> bool: ...

    async def mark_processed(self, event_id: str) -> None: ...


class InMemoryIdempotencyChecker:
    """Simple in-memory + Redis dedup (ported from Activity service)."""

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
            # Remove oldest 5000 entries (FIFO — first-inserted first evicted)
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
    - Configurable retry with exponential backoff via ``RetryPolicy``.
    - Dead-letter queue for malformed or exhausted messages.
    - Delayed requeue using a Redis sorted set + Lua pop script.
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

        self._redis: redis.Redis | None = None
        self._handlers: dict[str, EventHandler] = {}
        self._running = False
        self._dlq: DeadLetterHandler | None = None
        self._delayed_set = f"{stream_name}_delayed"
        self._delayed_poll_interval = 1.0
        self._delayed_task: asyncio.Task[None] | None = None

    # -- connection --

    async def connect(self) -> None:
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
        self._dlq = DeadLetterHandler(self._redis, self._stream_name, self._consumer_group)
        await self._ensure_consumer_group()

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

    # -- handler registration --

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

    # -- parsing --

    def _parse(self, message_id: str, data: dict[str, str]) -> EventEnvelope | None:
        try:
            if self._parse_mode == "payload":
                return EventEnvelope.from_payload_wrapper(message_id, data)
            return EventEnvelope.from_flat(message_id, data)
        except Exception:
            logger.exception("Failed to parse message %s", message_id)
            return None

    # -- processing --

    async def _process_message(self, message_id: str, data: dict[str, str]) -> bool:
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
            return True

        if self._idempotency and await self._idempotency.is_processed(envelope.event_id):
            logger.debug("Skipping duplicate event: %s", envelope.event_id)
            return True

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
            return True

        retry_count = envelope.metadata.get("retries", 0)
        try:
            await handler(envelope)
            if self._idempotency:
                await self._idempotency.mark_processed(envelope.event_id)
            logger.info("Processed event %s (%s)", envelope.event_id, envelope.event_type)
            return True
        except Exception as exc:
            logger.exception("Handler failed for event %s (attempt %d)", envelope.event_id, retry_count + 1)
            if retry_count < self._retry_policy.max_retries - 1:
                await self._requeue(message_id, data, retry_count + 1)
            else:
                if self._dlq:
                    try:
                        await self._dlq.move(message_id, data, f"Max retries exceeded: {exc!s}")
                    except Exception:
                        logger.exception("DLQ move failed for message %s — continuing", message_id)
            return True

    # -- retry / delayed requeue --

    async def _requeue(self, message_id: str, data: dict[str, str], retry_count: int) -> None:
        if self._redis is None:
            return
        try:
            if self._parse_mode == "payload":
                payload_str = data.get("payload")
                if payload_str:
                    payload = json.loads(payload_str)
                    payload.setdefault("metadata", {})["retries"] = retry_count
                    member = json.dumps({"payload": json.dumps(payload)})
                else:
                    return
            else:
                meta = json.loads(data.get("metadata", "{}"))
                meta["retries"] = retry_count
                updated = dict(data)
                updated["metadata"] = json.dumps(meta)
                member = json.dumps(updated)

            delay = self._retry_policy.delay_for(retry_count)
            deliver_at = time.time() + delay
            await self._redis.zadd(self._delayed_set, {member: deliver_at})
            logger.info("Scheduled retry %d for message %s (backoff %ds)", retry_count, message_id, delay)
        except Exception as exc:
            logger.exception("Failed to requeue message %s", message_id)
            if self._dlq:
                try:
                    await self._dlq.move(message_id, data, f"Requeue failed: {exc!s}")
                except Exception:
                    logger.exception("DLQ move also failed for message %s — continuing", message_id)

    async def _delayed_mover_loop(self) -> None:
        if self._redis is None:
            return
        lua = (
            "local members = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 100)\n"
            "if #members == 0 then return members end\n"
            "for i=1,#members do redis.call('ZREM', KEYS[1], members[i]) end\n"
            "return members\n"
        )
        while self._running:
            try:
                popped = await self._redis.eval(lua, 1, self._delayed_set, time.time())
                if popped:
                    for raw in popped:
                        try:
                            entry = json.loads(raw)
                            await self._redis.xadd(self._stream_name, entry, maxlen=100_000)
                        except Exception:
                            logger.exception("Failed to move delayed member to stream")
                await asyncio.sleep(self._delayed_poll_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in delayed mover loop")
                await asyncio.sleep(self._delayed_poll_interval)

    # -- ack --

    async def _ack(self, message_id: str) -> None:
        if self._redis:
            await self._redis.xack(self._stream_name, self._consumer_group, message_id)

    # -- main loop --

    async def start(self) -> None:
        await self.connect()
        self._running = True

        if self._retry_policy.max_retries > 0:
            self._delayed_task = asyncio.create_task(self._delayed_mover_loop())

        logger.info("Consumer started: %s on %s", self._consumer_name, self._stream_name)
        try:
            await self._consume_loop()
        finally:
            self._running = False
            if self._delayed_task:
                self._delayed_task.cancel()
                try:
                    await self._delayed_task
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
                        success = await self._process_message(msg_id, msg_data)
                        if success:
                            await self._ack(msg_id)
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

    async def stop(self) -> None:
        self._running = False
        await self.disconnect()

    @property
    def is_running(self) -> bool:
        return self._running
