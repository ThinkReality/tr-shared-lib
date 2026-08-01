from typing import Any

from tr_shared.middleware.correlation_id import CorrelationIDMiddleware
from tr_shared.middleware.error_handler import GlobalErrorHandlerMiddleware
from tr_shared.middleware.exception_handlers import (
    base_api_exception_handler,
    http_exception_handler,
    register_exception_handlers,
    validation_exception_handler,
)
from tr_shared.middleware.logging_middleware import LoggingMiddleware

__all__ = [
    "APIIdempotencyMiddleware",
    "CorrelationIDMiddleware",
    "GlobalErrorHandlerMiddleware",
    "LoggingMiddleware",
    "base_api_exception_handler",
    "http_exception_handler",
    "register_exception_handlers",
    "validation_exception_handler",
]

# APIIdempotencyMiddleware is the only member that needs the redis extra.
# Importing it eagerly made `from tr_shared.middleware import
# register_exception_handlers` raise ModuleNotFoundError: redis for any consumer
# without that extra — shared-auth-lib pins [http,logging] and so could not reach
# the error handlers it is required to install. Same lazy shape as
# tr_shared.monitoring's db/celery instrumentation.
_LAZY_IMPORTS = {
    "APIIdempotencyMiddleware": "tr_shared.middleware.idempotency",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        import importlib

        mod = importlib.import_module(_LAZY_IMPORTS[name])
        obj = getattr(mod, name)
        # Cache in module namespace so the next access is a normal attribute lookup.
        globals()[name] = obj
        return obj
    raise AttributeError(f"module 'tr_shared.middleware' has no attribute {name!r}")
