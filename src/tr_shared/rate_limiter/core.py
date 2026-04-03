"""Central RateLimiter class — delegates to algorithms, handles fallback.

All three usage patterns (middleware, dependency, decorator) delegate to this
class for the actual rate-limit check.
"""

import logging
import time
from typing import Any

from starlette.requests import Request

from tr_shared.monitoring.path_normalizer import normalize_path
from tr_shared.rate_limiter.algorithms import (
    BaseAlgorithm,
    FixedWindowAlgorithm,
    SlidingWindowAlgorithm,
)
from tr_shared.rate_limiter.memory_fallback import MemoryFallback
from tr_shared.rate_limiter.schemas import (
    Algorithm,
    FailMode,
    RateLimitConfig,
    RateLimitInfo,
    RateLimitResult,
    WindowConfig,
)

logger = logging.getLogger(__name__)

_ALGORITHMS: dict[Algorithm, BaseAlgorithm] = {
    Algorithm.FIXED_WINDOW: FixedWindowAlgorithm(),
    Algorithm.SLIDING_WINDOW: SlidingWindowAlgorithm(),
}

# Default config — 100 req/min fixed window, fail-open
_DEFAULT_CONFIG = RateLimitConfig()


class RateLimiter:
    """Redis-backed rate limiter with multi-window support and memory fallback.

    Args:
        redis_client: An existing async Redis client (preferred).
        redis_url: Or a Redis URL for lazy connection creation.
        key_prefix: Global prefix for all keys (e.g. ``"dev:lead"``).
        enable_memory_fallback: Use in-memory counters when Redis is down
            and ``fail_mode=OPEN``.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        redis_url: str = "",
        key_prefix: str = "",
        enable_memory_fallback: bool = True,
    ) -> None:
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._memory_fallback = MemoryFallback() if enable_memory_fallback else None

    async def _get_redis(self) -> Any | None:
        """Get or lazily create an async Redis client."""
        if self._redis_client is not None:
            return self._redis_client

        if self._redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis_client = aioredis.from_url(
                    self._redis_url, encoding="utf-8", decode_responses=True
                )
                return self._redis_client
            except Exception as e:
                logger.warning("Failed to connect to Redis for rate limiting: %s", e)
                return None

        return None

    async def check(
        self,
        key: str,
        config: RateLimitConfig | None = None,
    ) -> RateLimitInfo:
        """Check rate limit across all configured windows.

        Blocked if **any** window is exceeded.

        Args:
            key: The fully-qualified rate limit key.
            config: Rate limit configuration. Uses default (100/min) if None.

        Returns:
            Aggregated ``RateLimitInfo`` with per-window results.
        """
        cfg = config or _DEFAULT_CONFIG
        algorithm = _ALGORITHMS[cfg.algorithm]
        redis = await self._get_redis()

        results: list[RateLimitResult] = []
        is_blocked = False

        for window in cfg.windows:
            result = await self._check_window(
                redis=redis,
                algorithm=algorithm,
                key=key,
                window=window,
                fail_mode=cfg.fail_mode,
            )
            results.append(result)
            if not result.allowed:
                is_blocked = True

        return RateLimitInfo(results=results, is_blocked=is_blocked)

    async def _check_window(
        self,
        redis: Any | None,
        algorithm: BaseAlgorithm,
        key: str,
        window: WindowConfig,
        fail_mode: FailMode,
    ) -> RateLimitResult:
        """Check a single window, handling Redis failures gracefully."""
        window_key = f"{key}:{window.window_seconds}s"

        if redis is not None:
            try:
                return await algorithm.check(
                    redis_client=redis,
                    key=window_key,
                    limit=window.limit,
                    window_seconds=window.window_seconds,
                )
            except Exception as e:
                logger.error(
                    "Redis rate limit check failed, using fallback",
                    extra={"key": window_key, "error": str(e)},
                )

        # Redis unavailable or errored — decide based on fail_mode
        if fail_mode == FailMode.CLOSED:
            logger.warning(
                "Redis unavailable + fail_mode=CLOSED — blocking request",
                extra={"key": window_key},
            )
            return RateLimitResult(
                allowed=False,
                limit=window.limit,
                remaining=0,
                reset_at=0,
                retry_after=window.window_seconds,
            )

        # fail_mode=OPEN — use memory fallback if available
        if self._memory_fallback is not None:
            return await self._memory_fallback.check(
                key=window_key,
                limit=window.limit,
                window_seconds=window.window_seconds,
            )

        # No fallback — allow the request
        logger.warning(
            "Redis unavailable + no memory fallback — allowing request",
            extra={"key": window_key},
        )
        return RateLimitResult(
            allowed=True,
            limit=window.limit,
            remaining=window.limit,
            reset_at=0,
            retry_after=0,
        )

    async def reset(self, key: str, config: RateLimitConfig | None = None) -> bool:
        """Delete counters for a key across all configured windows.

        Returns:
            True if at least one key was deleted.
        """
        cfg = config or _DEFAULT_CONFIG
        redis = await self._get_redis()
        if redis is None:
            return False

        try:
            keys_to_delete = [f"{key}:{w.window_seconds}s" for w in cfg.windows]
            deleted = await redis.delete(*keys_to_delete)
            return deleted > 0
        except Exception as e:
            logger.error("Rate limit reset failed: %s", e)
            return False

    async def status(
        self, key: str, config: RateLimitConfig | None = None
    ) -> RateLimitInfo:
        """Get current rate limit status without incrementing.

        Falls back to an empty ``RateLimitInfo`` if Redis is unavailable.
        """
        cfg = config or _DEFAULT_CONFIG
        redis = await self._get_redis()
        if redis is None:
            return RateLimitInfo()

        results: list[RateLimitResult] = []
        is_blocked = False

        for window in cfg.windows:
            window_key = f"{key}:{window.window_seconds}s"
            try:
                count = int(await redis.get(window_key) or 0)
                remaining = max(0, window.limit - count)
                blocked = count > window.limit

                ttl = await redis.ttl(window_key)
                reset_at = int(time.time()) + max(ttl, 1)

                result = RateLimitResult(
                    allowed=not blocked,
                    limit=window.limit,
                    remaining=remaining,
                    reset_at=reset_at,
                    retry_after=max(ttl, 1) if blocked else 0,
                )
                results.append(result)
                if blocked:
                    is_blocked = True
            except Exception as e:
                logger.error("Rate limit status check failed: %s", e)

        return RateLimitInfo(results=results, is_blocked=is_blocked)

    def build_key(
        self,
        *,
        identifier: str,
        endpoint: str = "*",
        scope: str = "default",
    ) -> str:
        """Build a standardized rate limit key.

        Format: ``{prefix}:rl:{scope}:{identifier}:{normalized_endpoint}``

        Uses ``normalize_path`` from the monitoring module to replace
        UUIDs and numeric IDs with ``{id}`` for low-cardinality keys.

        Args:
            identifier: User ID, tenant ID, or IP address.
            endpoint: Request path (normalized automatically).
            scope: Logical grouping (e.g. ``"api"``, ``"webhook"``).
        """
        normalized = normalize_path(endpoint) if endpoint != "*" else "*"
        parts = [self._key_prefix, "rl", scope, identifier, normalized]
        return ":".join(p for p in parts if p)


def default_identifier_extractor(request: Request) -> str:
    """Extract rate-limit identifier: user_id > tenant_id > IP.

    Shared by both ``RateLimitMiddleware`` and ``create_rate_limit_dependency``
    to avoid duplicated logic.
    """
    if hasattr(request.state, "auth_context") and request.state.auth_context:
        ctx = request.state.auth_context
        if hasattr(ctx, "user_id") and ctx.user_id:
            return str(ctx.user_id)
        if hasattr(ctx, "tenant_id") and ctx.tenant_id:
            return str(ctx.tenant_id)

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"
