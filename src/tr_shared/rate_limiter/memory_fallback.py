"""In-memory rate limiter fallback when Redis is unavailable.

Extracted from tr-lead-management/app/core/rate_limiter.py (lines 113-153).
Uses asyncio.Lock for thread-safety and auto-cleans expired buckets.
"""

import asyncio
import logging
import time

from tr_shared.rate_limiter.schemas import RateLimitResult

logger = logging.getLogger(__name__)

DEFAULT_CLEANUP_THRESHOLD = 10_000


class MemoryFallback:
    """Thread-safe in-memory fixed-window rate limiter.

    Used as a fallback when Redis is unreachable and ``fail_mode=OPEN``.
    Not distributed — each process maintains its own counters.
    """

    def __init__(self, cleanup_threshold: int = DEFAULT_CLEANUP_THRESHOLD) -> None:
        self._buckets: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._cleanup_threshold = cleanup_threshold

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Check and increment the counter for *key*.

        Returns:
            A ``RateLimitResult`` reflecting the current window state.
        """
        now = time.time()

        async with self._lock:
            # Periodic cleanup when bucket count grows too large
            if len(self._buckets) > self._cleanup_threshold:
                await self._cleanup_expired(now)

            bucket = self._buckets.get(key)

            # New bucket or expired bucket — start fresh
            if bucket is None or now > bucket["reset_time"]:
                reset_time = now + window_seconds
                self._buckets[key] = {"count": 1, "reset_time": reset_time}
                return RateLimitResult(
                    allowed=True,
                    limit=limit,
                    remaining=max(0, limit - 1),
                    reset_at=int(reset_time),
                    retry_after=0,
                )

            # Bucket exists and is still active
            if bucket["count"] >= limit:
                retry_after = max(1, int(bucket["reset_time"] - now))
                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_at=int(bucket["reset_time"]),
                    retry_after=retry_after,
                )

            bucket["count"] += 1
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=max(0, limit - bucket["count"]),
                reset_at=int(bucket["reset_time"]),
                retry_after=0,
            )

    async def _cleanup_expired(self, now: float) -> None:
        """Remove expired buckets to bound memory usage."""
        expired = [k for k, v in self._buckets.items() if now > v["reset_time"]]
        for k in expired:
            del self._buckets[k]
        if expired:
            logger.debug(
                "Memory fallback cleanup: removed %d expired buckets", len(expired)
            )
