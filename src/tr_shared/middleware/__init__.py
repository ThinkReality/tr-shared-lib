"""Shared FastAPI middleware."""

from tr_shared.middleware.correlation_id import CorrelationIDMiddleware
from tr_shared.middleware.error_handler import GlobalErrorHandlerMiddleware
from tr_shared.middleware.idempotency import APIIdempotencyMiddleware
from tr_shared.middleware.logging_middleware import LoggingMiddleware

__all__ = [
    "APIIdempotencyMiddleware",
    "CorrelationIDMiddleware",
    "GlobalErrorHandlerMiddleware",
    "LoggingMiddleware",
]
