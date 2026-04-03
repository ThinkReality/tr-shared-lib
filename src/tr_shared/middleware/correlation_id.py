"""
Correlation ID middleware — generates or propagates X-Correlation-ID.

Extracted from tr-notification-service. Identical 15-line implementation
duplicated across all services.

Usage::

    from tr_shared.middleware import CorrelationIDMiddleware
    app.add_middleware(CorrelationIDMiddleware)
"""

import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Propagate or generate X-Correlation-ID on every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
