"""Redis-based webhook idempotency guard.

Uses atomic ``SET NX EX`` to ensure each webhook event is processed at most
once. Follows fail-open semantics: if Redis is unavailable, the event is
treated as non-duplicate to avoid silently dropping webhooks.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WebhookIdempotencyGuard:
    """Deduplicates webhook deliveries using Redis SET NX.

    Key format: ``{key_prefix}:webhook:{provider}:{event_id}:processed``
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        redis_url: str = "",
        key_prefix: str = "",
        default_ttl: int = 86400,
    ) -> None:
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._default_ttl = default_ttl

    async def _get_redis(self) -> Any | None:
        if self._redis_client is not None:
            return self._redis_client

        if not self._redis_url:
            return None

        try:
            from tr_shared.redis.client import get_redis_client

            self._redis_client = await get_redis_client(self._redis_url)
            return self._redis_client
        except Exception:
            logger.warning("Failed to connect to Redis for idempotency", exc_info=True)
            return None

    def build_key(self, provider: str, event_id: str) -> str:
        """Build the idempotency Redis key."""
        parts = [p for p in (self._key_prefix, "webhook", provider, event_id, "processed") if p]
        return ":".join(parts)

    async def is_duplicate(
        self,
        provider: str,
        event_id: str,
        ttl: int | None = None,
    ) -> bool:
        """Check if this webhook event has already been processed.

        Fail-open: on Redis failure, returns ``False`` (non-duplicate) rather
        than dropping the webhook.
        """
        if not event_id:
            return False

        redis = await self._get_redis()
        if redis is None:
            return False

        key = self.build_key(provider, event_id)
        effective_ttl = ttl or self._default_ttl

        try:
            was_set = await redis.set(key, "1", nx=True, ex=effective_ttl)
        except Exception:
            logger.warning(
                "Idempotency check failed — treating as non-duplicate (fail-open)",
                extra={"provider": provider, "event_id": event_id},
                exc_info=True,
            )
            return False

        # SET NX returns True if key was newly set, None if it already existed
        return was_set is None

    async def mark_processed(
        self,
        provider: str,
        event_id: str,
        ttl: int | None = None,
    ) -> None:
        """Explicitly mark an event as processed.

        Useful when idempotency check is deferred (e.g. checked at task level).
        """
        if not event_id:
            return

        redis = await self._get_redis()
        if redis is None:
            return

        key = self.build_key(provider, event_id)
        effective_ttl = ttl or self._default_ttl

        try:
            await redis.set(key, "1", ex=effective_ttl)
        except Exception:
            logger.warning(
                "Failed to mark event as processed",
                extra={"provider": provider, "event_id": event_id},
                exc_info=True,
            )
