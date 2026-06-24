import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import redis.asyncio as redis
from redis.exceptions import RedisError

from tr_shared.contracts.taxonomy import Feature
from tr_shared.events.exceptions import EventPublishTransportError

logger = logging.getLogger(__name__)


class EventProducer:
    STREAM_MAXLEN = 100_000
    DEFAULT_MAX_DATA_BYTES = 1_048_576  # 1 MB

    def __init__(
        self,
        redis_url: str | None = None,
        stream_name: str = "tr_event_bus",
        *,
        source_service: Feature | str,
        maxlen: int | None = None,
        max_data_bytes: int = DEFAULT_MAX_DATA_BYTES,
    ) -> None:
        self._redis_url = redis_url
        self._stream_name = stream_name
        self._source_service = self._normalize_source(source_service)
        self._maxlen = maxlen or self.STREAM_MAXLEN
        self._max_data_bytes = max_data_bytes
        self._redis: redis.Redis | None = None

    @staticmethod
    def _normalize_source(source: Feature | str) -> str:
        """Enforce the locked invariant: event source is ALWAYS a Feature value,
        never a deployable name. Accepts a Feature or its string value; rejects
        anything else (including the old ``"unknown"`` sentinel) at construction."""
        try:
            return str(Feature(str(source)))
        except ValueError as exc:
            valid = ", ".join(f.value for f in Feature)
            raise ValueError(
                f"EventProducer source_service must be a Feature value, "
                f"got {source!r}. Valid Feature values: {valid}"
            ) from exc

    async def connect(self) -> None:
        if self._redis is None and self._redis_url:
            try:
                self._redis = redis.from_url(self._redis_url, decode_responses=True)
            except Exception:
                logger.warning("EventProducer initial connect failed, retrying once")
                await asyncio.sleep(1)
                self._redis = redis.from_url(self._redis_url, decode_responses=True)

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None

    def set_redis(self, client: redis.Redis) -> None:
        self._redis = client

    async def publish(
        self,
        event_type: str,
        tenant_id: str,
        data: dict[str, Any],
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        strict_mode: bool = False,
    ) -> str:
        if strict_mode:
            for field in ("entity_id", "entity_type", "action"):
                if field not in data:
                    raise ValueError(f"data must contain '{field}'")

        if self._max_data_bytes:
            data_size = len(json.dumps(data).encode())
            if data_size > self._max_data_bytes:
                raise ValueError(
                    f"Event data is {data_size} bytes, "
                    f"exceeds limit of {self._max_data_bytes} bytes"
                )

        event_id = str(uuid4())
        event_metadata = metadata.copy() if metadata else {}
        if correlation_id:
            event_metadata["correlation_id"] = correlation_id

        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "version": "1.0",
            "tenant_id": tenant_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "source_service": self._source_service,
            "actor_id": actor_id or "",
            "data": json.dumps(data),
            "metadata": json.dumps(event_metadata),
        }

        if self._redis is None:
            await self.connect()
        if self._redis is None:
            raise RuntimeError("Redis connection not available")

        # CRITICAL: This direct XADD gives AT-MOST-ONCE delivery and does NOT
        # enforce ordering relative to the caller's DB transaction. The producer
        # publishes immediately when called; whether that happens before or after
        # the caller's commit is the CALLER'S responsibility. Calling publish()
        # before the transaction commits risks a PHANTOM EVENT (event delivered,
        # business data later rolled back); calling it after commit risks a LOST
        # EVENT if Redis is down (no in-flight retry). The post-commit, accept-loss
        # tradeoff is acceptable at current scale.
        # For AT-LEAST-ONCE with no phantom events, do NOT call this directly —
        # use DurableEventPublisher (transactional outbox): it writes the event to
        # an outbox table inside the caller's transaction, and a background drainer
        # publishes committed rows via this same XADD.
        try:
            await self._redis.xadd(self._stream_name, envelope, maxlen=self._maxlen)
        except RedisError as exc:
            logger.error(
                "Failed to publish event",
                extra={
                    "event_id": event_id,
                    "event_type": event_type,
                    "stream": self._stream_name,
                    "metric": "event_publish_failed",
                },
            )
            raise EventPublishTransportError(
                f"Failed to publish {event_type!r} to {self._stream_name!r}: {exc}"
            ) from exc
        logger.info(
            "Published event",
            extra={
                "event_id": event_id,
                "event_type": event_type,
                "stream": self._stream_name,
                "metric": "event_published",
            },
        )
        return event_id
