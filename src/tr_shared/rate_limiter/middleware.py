"""Starlette middleware for global rate limiting.

Supports all existing service patterns:
- All methods (default)
- Write-method-only (HR, admin-panel): ``methods=["POST","PUT","PATCH","DELETE"]``
- IP whitelisting (gateway)
- Custom identifier extraction (media-service tenant-scoped)
"""

import logging
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from tr_shared.rate_limiter.core import RateLimiter, default_identifier_extractor
from tr_shared.rate_limiter.schemas import RateLimitConfig

logger = logging.getLogger(__name__)

# Paths that are always excluded from rate limiting
_DEFAULT_EXCLUDED = frozenset(
    {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/metrics",
    }
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global rate limiting middleware.

    Args:
        app: ASGI application.
        limiter: Shared ``RateLimiter`` instance.
        config: Rate limit configuration. Defaults to 100 req/min.
        excluded_paths: Paths to skip (merged with built-in defaults).
        whitelist_ips: IP addresses exempt from rate limiting.
        identifier_extractor: Custom ``(request) -> str`` to extract
            the rate limit identifier.
    """

    def __init__(
        self,
        app,
        limiter: RateLimiter,
        config: RateLimitConfig | None = None,
        excluded_paths: frozenset[str] | None = None,
        whitelist_ips: list[str] | None = None,
        identifier_extractor: Callable[[Request], str] | None = None,
    ) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.config = config or RateLimitConfig()
        self.excluded_paths = _DEFAULT_EXCLUDED | (excluded_paths or frozenset())
        self.whitelist_ips = set(whitelist_ips) if whitelist_ips else set()
        self.identifier_extractor = (
            identifier_extractor or default_identifier_extractor
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip excluded paths (prefix match — e.g., "/internal" matches "/internal/status")
        if any(path.startswith(ep) for ep in self.excluded_paths):
            return await call_next(request)

        # Skip if method filter is set and method doesn't match
        if self.config.methods and request.method.upper() not in self.config.methods:
            return await call_next(request)

        # Skip whitelisted IPs
        client_ip = request.client.host if request.client else ""
        if client_ip in self.whitelist_ips:
            return await call_next(request)

        # Extract identifier and build key
        identifier = self.identifier_extractor(request)
        key = self.limiter.build_key(
            identifier=identifier,
            endpoint=path,
            scope=self.config.key_prefix,
        )

        # Check rate limit
        info = await self.limiter.check(key=key, config=self.config)

        if info.is_blocked:
            # Find the most restrictive window for retry-after
            retry_after = max(
                (r.retry_after for r in info.results if not r.allowed), default=60
            )
            tightest = next((r for r in info.results if not r.allowed), info.results[0])

            logger.warning(
                "Rate limit exceeded",
                extra={
                    "identifier": identifier,
                    "path": path,
                    "limit": tightest.limit,
                    "retry_after": retry_after,
                },
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Rate limit exceeded. Please try again later.",
                    }
                },
                headers={
                    "X-RateLimit-Limit": str(tightest.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(tightest.reset_at),
                    "Retry-After": str(retry_after),
                },
            )

        # Add rate limit headers to successful response
        response = await call_next(request)

        if info.results:
            tightest = min(info.results, key=lambda r: r.remaining)
            response.headers["X-RateLimit-Limit"] = str(tightest.limit)
            response.headers["X-RateLimit-Remaining"] = str(tightest.remaining)
            response.headers["X-RateLimit-Reset"] = str(tightest.reset_at)

        return response
