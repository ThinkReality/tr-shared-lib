"""
Layer 2 persistence middleware — captures per-request details with
tenant/user context and pushes to a Redis buffer.

Unlike the Layer 1 ``MetricsMiddleware`` (which writes low-cardinality
labels to Prometheus), this middleware captures **high-cardinality**
fields (``tenant_id``, ``user_id``, request/response sizes) for
storage in the central monitoring PostgreSQL database.

The Redis RPUSH is fire-and-forget (<1ms) — a Celery task flushes
the buffer to PostgreSQL every 60 seconds.

**Must be added AFTER** ``IdentityExtractionMiddleware`` (shared-auth-lib)
so that ``request.state.auth_context`` is populated.

Usage::

    from tr_shared.monitoring.persistence import PersistenceMiddleware

    app.add_middleware(
        PersistenceMiddleware,
        service_name="crm-backend",
        redis_url="redis://localhost:6379/0",
    )
"""

import logging
import time
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from tr_shared.monitoring.path_normalizer import normalize_path

logger = logging.getLogger(__name__)

_DEFAULT_EXCLUDED_PATHS: frozenset[str] = frozenset({
    "/",
    "/health",
    "/health/ready",
    "/health/live",
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/health/live",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
})


class PersistenceMiddleware(BaseHTTPMiddleware):
    """
    Fire-and-forget request logging to Redis buffer.

    Captures tenant_id, user_id, response time, sizes, and error
    details for every non-excluded request.

    Args:
        app: ASGI application.
        service_name: Included in every persisted record.
        redis_url: Redis connection URL for the buffer.
        excluded_paths: Paths to skip (defaults match Layer 1).
    """

    def __init__(
        self,
        app,
        service_name: str = "unknown",
        redis_url: str = "",
        excluded_paths: frozenset[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.redis_url = redis_url
        self.excluded_paths = excluded_paths or _DEFAULT_EXCLUDED_PATHS
        self._redis_client = None

    async def _get_redis(self):
        """Lazy-init async Redis client."""
        if self._redis_client is None:
            try:
                from redis.asyncio import Redis
                self._redis_client = Redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
            except Exception as exc:
                logger.error("Failed to create Redis client for monitoring: %s", exc)
        return self._redis_client

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        start = time.perf_counter()
        error_message = None
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response

        except Exception as exc:
            error_message = str(exc)[:500]
            raise

        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            await self._persist_record(
                request=request,
                status_code=status_code,
                duration_ms=duration_ms,
                error_message=error_message,
            )

    async def _persist_record(
        self,
        request: Request,
        status_code: int,
        duration_ms: int,
        error_message: str | None,
    ) -> None:
        """Build a record dict and push to Redis buffer (fire-and-forget)."""
        try:
            user_id, tenant_id = self._extract_identity(request)
            now = datetime.now(UTC)

            record = {
                "service_name": self.service_name,
                "endpoint": normalize_path(request.url.path),
                "method": request.method,
                "status_code": status_code,
                "response_time_ms": duration_ms,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "request_size_bytes": self._get_content_length(request),
                "correlation_id": getattr(request.state, "correlation_id", None),
                "error_message": error_message,
                "timestamp": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "hour": now.hour,
            }

            redis = await self._get_redis()
            if redis:
                from tr_shared.monitoring.redis_buffer import push_to_buffer
                await push_to_buffer(redis, self.service_name, record)

        except Exception as exc:
            # Never let persistence failure break the request
            logger.warning("Monitoring persistence error: %s", exc)

    @staticmethod
    def _extract_identity(request: Request) -> tuple[str | None, str | None]:
        """
        Extract user_id and tenant_id from auth context.

        Cascading pattern (same as error_handler.py):
        1. request.state.auth_context (shared-auth-lib)
        2. request.state.user (legacy dict or object)
        3. X-Tenant-ID / X-User-ID headers (S2S calls)
        """
        # 1. shared-auth-lib AuthContext
        auth_ctx = getattr(request.state, "auth_context", None)
        if auth_ctx:
            return (
                str(getattr(auth_ctx, "user_id", None) or ""),
                str(getattr(auth_ctx, "tenant_id", None) or ""),
            )

        # 2. Legacy request.state.user
        user = getattr(request.state, "user", None)
        if user is not None:
            if hasattr(user, "get"):
                return user.get("id"), user.get("tenant_id")
            return str(getattr(user, "id", None)), str(getattr(user, "tenant_id", None))

        # 3. Headers (S2S calls where identity is in headers)
        tenant_id = request.headers.get("x-tenant-id")
        user_id = request.headers.get("x-user-id")
        if tenant_id or user_id:
            return user_id, tenant_id

        return None, None

    @staticmethod
    def _get_content_length(request: Request) -> int | None:
        """Extract Content-Length header, or None."""
        cl = request.headers.get("content-length")
        if cl:
            try:
                return int(cl)
            except (ValueError, TypeError):
                pass
        return None
