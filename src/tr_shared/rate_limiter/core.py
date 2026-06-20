import logging
import time
from typing import Any

import redis.asyncio as aioredis
from starlette.requests import Request

from tr_shared.contracts.headers import HttpHeader
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
        if self._redis_client is not None:
            return self._redis_client

        if self._redis_url:
            try:
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
        """Blocked if **any** window is exceeded."""
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

        if self._memory_fallback is not None:
            return await self._memory_fallback.check(
                key=window_key,
                limit=window.limit,
                window_seconds=window.window_seconds,
            )

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
        """Get current rate limit status without incrementing."""
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
        """Format: ``{prefix}:rl:{scope}:{identifier}:{normalized_endpoint}``

        Uses ``normalize_path`` to replace UUIDs and numeric IDs with ``{id}`` for low-cardinality keys.
        """
        normalized = normalize_path(endpoint) if endpoint != "*" else "*"
        parts = [self._key_prefix, "rl", scope, identifier, normalized]
        return ":".join(p for p in parts if p)


def default_identifier_extractor(request: Request) -> str:
    """Extract rate-limit identifier: user_id > tenant_id > IP."""
    if hasattr(request.state, "auth_context") and request.state.auth_context:
        ctx = request.state.auth_context
        if hasattr(ctx, "user_id") and ctx.user_id:
            return str(ctx.user_id)
        if hasattr(ctx, "tenant_id") and ctx.tenant_id:
            return str(ctx.tenant_id)

    forwarded_for = request.headers.get(HttpHeader.FORWARDED_FOR.value)
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get(HttpHeader.REAL_IP.value)
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"
