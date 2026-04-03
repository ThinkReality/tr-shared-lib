"""Rate limiting algorithm implementations.

Two strategies extracted from existing services:
- FixedWindowAlgorithm: INCR+EXPIRE (fastest, least memory)
- SlidingWindowAlgorithm: ZSET-based (more precise distribution)
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from tr_shared.rate_limiter.lua_scripts import FIXED_WINDOW_LUA, SLIDING_WINDOW_LUA
from tr_shared.rate_limiter.schemas import RateLimitResult

logger = logging.getLogger(__name__)


class BaseAlgorithm(ABC):
    """Abstract base for rate limiting algorithms."""

    @abstractmethod
    async def check(
        self, redis_client: Any, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        """Check and increment the rate limit counter.

        Args:
            redis_client: An async Redis client with ``eval()`` support.
            key: The fully-qualified Redis key.
            limit: Maximum requests allowed in the window.
            window_seconds: Window duration in seconds.

        Returns:
            A ``RateLimitResult`` reflecting the current window state.
        """
        ...


class FixedWindowAlgorithm(BaseAlgorithm):
    """INCR + EXPIRE fixed-window counter.

    Fastest and least memory. Used by: lead-management, HR, admin-panel, crm-backend.
    """

    async def check(
        self, redis_client: Any, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        result = await redis_client.eval(
            FIXED_WINDOW_LUA,
            1,  # number of keys
            key,  # KEYS[1]
            limit,  # ARGV[1]
            window_seconds,  # ARGV[2]
        )

        count = int(result[0])
        is_over = bool(result[1])
        ttl = int(result[2]) if len(result) > 2 else window_seconds

        now = int(time.time())
        reset_at = now + max(ttl, 1)
        remaining = max(0, limit - count)
        retry_after = max(1, ttl) if is_over else 0

        return RateLimitResult(
            allowed=not is_over,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )


class SlidingWindowAlgorithm(BaseAlgorithm):
    """ZSET-based sliding window. More precise distribution.

    Used by: gateway, media-service.
    """

    async def check(
        self, redis_client: Any, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        now = time.time()

        result = await redis_client.eval(
            SLIDING_WINDOW_LUA,
            1,  # number of keys
            key,  # KEYS[1]
            now,  # ARGV[1] — current timestamp
            window_seconds,  # ARGV[2] — window size
            limit,  # ARGV[3] — limit
        )

        count = int(result[0])
        is_over = bool(result[1])

        reset_at = int(now) + window_seconds
        remaining = max(0, limit - count)
        retry_after = window_seconds if is_over else 0

        return RateLimitResult(
            allowed=not is_over,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )
