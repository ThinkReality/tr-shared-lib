"""
SQLAlchemy database query instrumentation via OTel.

Attaches ``before_cursor_execute`` and ``after_cursor_execute`` event listeners
to a SQLAlchemy ``AsyncEngine`` that record two metrics:

- ``db_client_operation_duration_seconds`` — histogram of query wall-clock time.
- ``db_client_operations`` — counter of queries, labelled by operation type.

**Must be called AFTER** ``setup_monitoring()`` so the global ``MeterProvider``
is configured.  Calling before ``setup_monitoring()`` results in a no-op
(noop) meter.

Usage::

    from tr_shared.monitoring import setup_db_instrumentation
    from app.core.database import async_engine

    # in main.py, after setup_monitoring(...)
    setup_db_instrumentation(engine=async_engine)
"""

import logging
import time

from opentelemetry import metrics
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_VALID_OPERATIONS: frozenset[str] = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})


def _extract_operation_type(statement: str | None) -> str:
    """Return the SQL verb for *statement* or ``'UNKNOWN'`` / ``'OTHER'``."""
    if not statement:
        return "UNKNOWN"
    stripped = statement.strip()
    if not stripped:
        return "UNKNOWN"
    first_word = stripped.split()[0].upper()
    return first_word if first_word in _VALID_OPERATIONS else "OTHER"


def setup_db_instrumentation(engine: AsyncEngine) -> None:
    """Attach OTel query metrics to *engine*.

    Args:
        engine: The ``AsyncEngine`` to instrument.  Listeners are registered
            on ``engine.sync_engine`` as required by SQLAlchemy's event system.
    """
    meter = metrics.get_meter("tr_shared.monitoring.db")

    db_query_duration = meter.create_histogram(
        "db_client_operation_duration_seconds",
        description="Database query duration",
        unit="s",
    )
    db_operation_counter = meter.create_counter(
        "db_client_operations",
        description="Total database operations",
        unit="{operation}",
    )

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start_time = getattr(context, "_query_start_time", None)
        if start_time is None:
            return

        duration = time.perf_counter() - start_time
        operation = _extract_operation_type(statement)
        labels = {"db.system": "postgresql", "db.operation": operation}

        db_query_duration.record(duration, labels)
        db_operation_counter.add(1, labels)

    logger.info("DB query instrumentation attached to engine %r", engine)
