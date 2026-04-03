"""
Shared structured logging configuration using structlog.

Extracted from crm-backend and tr-notification-service — identical ~80-line
implementations across 10+ services.

Usage::

    from tr_shared.logging import configure_logging, get_logger

    # In main.py lifespan (call once at startup)
    configure_logging(log_level="INFO", log_format="json")

    # Anywhere else
    logger = get_logger(__name__)
    logger.info("hello", tenant_id="...", extra_field="value")
"""

import logging
import re
import sys
from typing import Any

import structlog

# Field names whose values should be masked in log output.
_SENSITIVE_PATTERNS = re.compile(
    r"(token|secret|password|key|authorization|credential)",
    re.IGNORECASE,
)


def _mask_sensitive_fields(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that masks values of sensitive fields."""
    for field_name, value in event_dict.items():
        if isinstance(value, str) and _SENSITIVE_PATTERNS.search(field_name):
            if len(value) > 6:
                event_dict[field_name] = value[:3] + "***" + value[-3:]
            elif value:
                event_dict[field_name] = "***"
    return event_dict


def configure_logging(
    log_level: str = "INFO",
    log_format: str = "text",
    service_name: str = "",
) -> None:
    """
    Configure structlog for the service.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: "json" for production, "text" for local dev (colored output).
        service_name: If provided, bound as a default context variable so every
            log record includes ``service_name`` without callers having to
            pass it explicitly.
    """
    if service_name:
        structlog.contextvars.bind_contextvars(service_name=service_name)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _mask_sensitive_fields,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named structlog logger instance."""
    return structlog.get_logger(name)


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID into structlog contextvars.

    Call this at the start of any non-HTTP context (Celery tasks, CLI scripts)
    that makes service-to-service calls via ``ServiceHTTPClient``. The client
    reads ``correlation_id`` from contextvars to auto-inject ``X-Correlation-ID``.

    Usage in a Celery task::

        from tr_shared.logging import bind_correlation_id

        @celery_app.task
        def my_task(correlation_id: str | None = None):
            if correlation_id:
                bind_correlation_id(correlation_id)
            # ... ServiceHTTPClient calls now propagate the ID automatically
    """
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
