"""
Request/response logging middleware.

Extracted from tr-listing-service — structured logging of every request
with duration, correlation ID, tenant context, and client IP.

Usage::

    from tr_shared.middleware import LoggingMiddleware

    app.add_middleware(LoggingMiddleware, service_name="tr-listing-service")
"""

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_PATHS: set[str] = {
    "/",
    "/health",
    "/health/ready",
    "/health/live",
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/health/live",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
}


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Log every HTTP request with method, path, status, and duration.

    Args:
        app: ASGI application.
        service_name: Included in every log line for filtering.
        excluded_paths: Paths to skip (defaults to health/docs/metrics).
    """

    def __init__(
        self,
        app,
        service_name: str = "unknown",
        excluded_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.excluded_paths = excluded_paths or DEFAULT_EXCLUDED_PATHS

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        start = time.perf_counter()
        meta = self._extract_metadata(request)

        logger.info("Request started", extra={"service": self.service_name, "event": "request_started", **meta})

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "Request failed",
                extra={
                    "service": self.service_name,
                    "event": "request_failed",
                    "duration_ms": round(duration_ms, 2),
                    "error_type": type(exc).__name__,
                    "error_summary": str(exc)[:200],
                    **meta,
                },
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        level = "info" if response.status_code < 400 else "warning"
        getattr(logger, level)(
            "Request completed",
            extra={
                "service": self.service_name,
                "event": "request_completed",
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                **meta,
            },
        )
        return response

    @staticmethod
    def _extract_metadata(request: Request) -> dict:
        meta: dict = {
            "method": request.method,
            "path": request.url.path,
        }
        if request.query_params:
            meta["query_string"] = str(request.query_params)

        # Client IP (respect X-Forwarded-For)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            meta["client_ip"] = forwarded.split(",")[0].strip()
        elif request.client:
            meta["client_ip"] = request.client.host

        ua = request.headers.get("User-Agent")
        if ua:
            meta["user_agent"] = ua

        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id:
            meta["correlation_id"] = correlation_id

        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            meta["tenant_id"] = tenant_id

        return meta
