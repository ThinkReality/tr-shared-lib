"""Per-message retry-attempt counter for the PEL-based consumer retry path.

``XCLAIM``/``XAUTOCLAIM`` preserve the original ``message_id`` and never let us
mutate the stream entry, so the attempt count cannot live in the payload. It
lives here instead: one Redis hash per ``(stream, consumer_group)``, keyed by
``message_id``, with a TTL that refreshes on every increment so abandoned hashes
self-clean.
"""

from __future__ import annotations

import redis.asyncio as redis


class RetryStateStore:
    """Tracks handler-failure attempts per ``(stream, group, message_id)``."""

    def __init__(
        self,
        redis_client: redis.Redis,
        stream_name: str,
        consumer_group: str,
        ttl_seconds: int = 86_400,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._key = f"{stream_name}:{consumer_group}:retries"

    async def increment(self, message_id: str) -> int:
        count = await self._redis.hincrby(self._key, message_id, 1)
        await self._redis.expire(self._key, self._ttl)
        return count

    async def get(self, message_id: str) -> int:
        value = await self._redis.hget(self._key, message_id)
        return int(value) if value is not None else 0

    async def clear(self, message_id: str) -> None:
        await self._redis.hdel(self._key, message_id)
