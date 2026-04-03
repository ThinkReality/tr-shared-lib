"""Unified event producer for publishing to Redis Stream."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class EventProducer:
    """Publishes events to a Redis Stream using the canonical 9-field envelope."""

    STREAM_MAXLEN = 100_000
    DEFAULT_MAX_DATA_BYTES = 1_048_576  # 1 MB

    def __init__(
        self,
        redis_url: str | None = None,
        stream_name: str = "tr_event_bus",
        source_service: str = "unknown",
        maxlen: int | None = None,
        max_data_bytes: int = DEFAULT_MAX_DATA_BYTES,
    ) -> None:
        self._redis_url = redis_url
        self._stream_name = stream_name
        self._source_service = source_service
        self._maxlen = maxlen or self.STREAM_MAXLEN
        self._max_data_bytes = max_data_bytes
        self._redis: redis.Redis | None = None

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
        """Inject an existing Redis client (useful for shared connections)."""
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
        """Publish an event to the Redis Stream.

        Args:
            event_type: Dot-separated event type (e.g. "listing.created").
            tenant_id: Tenant UUID string.
            data: Event payload dict.
            actor_id: Optional user UUID who triggered the event.
            metadata: Optional extra metadata dict.
            correlation_id: Optional correlation ID for tracing.
            strict_mode: If True, require entity_id/entity_type/action in data.

        Returns:
            The generated event_id (UUID string).

        Raises:
            ValueError: If strict_mode is True and required fields are missing.
            RuntimeError: If Redis is not connected.
        """
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

        # CRITICAL: Delivery guarantee is AT-MOST-ONCE.
        # This XADD runs AFTER the caller's DB transaction has committed.
        # If Redis is down or XADD fails, the event is lost while the DB
        # change persists. This is acceptable at current scale.
        # If exactly-once delivery is ever required (e.g., for financial
        # transactions), implement a transactional outbox pattern: write
        # the event to an outbox table inside the same DB transaction,
        # then have a separate worker poll and publish to Redis.
        try:
            await self._redis.xadd(self._stream_name, envelope, maxlen=self._maxlen)
        except Exception:
            logger.error(
                "Failed to publish event",
                extra={
                    "event_id": event_id,
                    "event_type": event_type,
                    "stream": self._stream_name,
                    "metric": "event_publish_failed",
                },
            )
            raise
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
