import logging
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from tr_shared.contracts.headers import HttpHeader
from tr_shared.rate_limiter.core import RateLimiter, default_identifier_extractor
from tr_shared.rate_limiter.schemas import RateLimitConfig

logger = logging.getLogger(__name__)

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

        if self.config.methods and request.method.upper() not in self.config.methods:
            return await call_next(request)

        client_ip = request.client.host if request.client else ""
        if client_ip in self.whitelist_ips:
            return await call_next(request)

        identifier = self.identifier_extractor(request)
        key = self.limiter.build_key(
            identifier=identifier,
            endpoint=path,
            scope=self.config.key_prefix,
        )

        info = await self.limiter.check(key=key, config=self.config)

        if info.is_blocked:
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
                    HttpHeader.RATE_LIMIT_LIMIT.value: str(tightest.limit),
                    HttpHeader.RATE_LIMIT_REMAINING.value: "0",
                    HttpHeader.RATE_LIMIT_RESET.value: str(tightest.reset_at),
                    "Retry-After": str(retry_after),
                },
            )

        response = await call_next(request)

        if info.results:
            tightest = min(info.results, key=lambda r: r.remaining)
            response.headers[HttpHeader.RATE_LIMIT_LIMIT.value] = str(tightest.limit)
            response.headers[HttpHeader.RATE_LIMIT_REMAINING.value] = str(
                tightest.remaining
            )
            response.headers[HttpHeader.RATE_LIMIT_RESET.value] = str(tightest.reset_at)

        return response
