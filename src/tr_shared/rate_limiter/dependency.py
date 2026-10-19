import logging
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from tr_shared.contracts.headers import HttpHeader
from tr_shared.rate_limiter.core import RateLimiter
from tr_shared.rate_limiter.schemas import (
    Algorithm,
    FailMode,
    RateLimitConfig,
    WindowConfig,
)

logger = logging.getLogger(__name__)


def create_rate_limit_dependency(
    limiter: RateLimiter,
    *,
    identifier: Callable[..., Any],
    limit: int = 100,
    window: int = 60,
    algorithm: Algorithm = Algorithm.FIXED_WINDOW,
    key_prefix: str = "api",
    fail_mode: FailMode = FailMode.OPEN,
) -> Callable:
    config = RateLimitConfig(
        windows=[WindowConfig(limit=limit, window_seconds=window)],
        algorithm=algorithm,
        fail_mode=fail_mode,
        key_prefix=key_prefix,
    )

    async def dependency(request: Request, caller: str = Depends(identifier)) -> None:
        key = limiter.build_key(
            identifier=caller,
            endpoint=request.url.path,
            scope=key_prefix,
        )

        info = await limiter.check(key=key, config=config)

        if info.is_blocked:
            tightest = next((r for r in info.results if not r.allowed), info.results[0])
            retry_after = max(1, tightest.retry_after)

            logger.warning(
                "Rate limit exceeded (dependency)",
                extra={
                    "identifier": caller,
                    "path": request.url.path,
                    "limit": tightest.limit,
                    "retry_after": retry_after,
                },
            )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={
                    HttpHeader.RATE_LIMIT_LIMIT.value: str(tightest.limit),
                    HttpHeader.RATE_LIMIT_REMAINING.value: "0",
                    HttpHeader.RATE_LIMIT_RESET.value: str(tightest.reset_at),
                    HttpHeader.RETRY_AFTER.value: str(retry_after),
                },
            )

        request.state.rate_limit_info = info

    return dependency
