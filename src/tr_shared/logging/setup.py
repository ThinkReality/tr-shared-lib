"""
Shared structured logging configuration using structlog.

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
from collections.abc import MutableMapping
from typing import Any

import structlog

# Field names whose values should be masked in log output.
_SENSITIVE_PATTERNS = re.compile(
    r"(token|secret|password|passwd|pwd|api_?key|key|authorization|auth"
    r"|credential|private_key|database_url|redis_url)",
    re.IGNORECASE,
)

_REDACTED = "[REDACTED]"


def _mask_sensitive_fields(
    logger: Any, method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Structlog processor that fully redacts values of sensitive fields."""
    for field_name, value in event_dict.items():
        if isinstance(value, str) and value and _SENSITIVE_PATTERNS.search(field_name):
            event_dict[field_name] = _REDACTED
    return event_dict


_extra_adder = structlog.stdlib.ExtraAdder()


def _add_stdlib_extras(
    logger: Any, method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    message = event_dict["event"]
    _extra_adder(logger, method, event_dict)
    if event_dict["event"] != message:
        event_dict["extra_event"] = event_dict["event"]
        event_dict["event"] = message
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
        _add_stdlib_extras,
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
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter_processors: list[structlog.types.Processor] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
    ]
    if log_format == "json":
        formatter_processors.append(structlog.processors.format_exc_info)
    formatter_processors.append(renderer)

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=formatter_processors,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID into structlog contextvars.

    HTTP requests and Celery tasks are bound automatically by
    ``CorrelationIDMiddleware`` and the hooks ``create_celery_app`` installs. Call
    this only from other contexts, such as CLI scripts, that make service-to-service
    calls via ``ServiceHTTPClient``, which reads ``correlation_id`` from contextvars
    to inject ``X-Correlation-ID``.
    """
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def get_correlation_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("correlation_id")
