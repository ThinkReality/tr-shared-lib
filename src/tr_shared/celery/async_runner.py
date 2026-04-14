"""
Utility for running async coroutines inside Celery worker processes.

Celery workers are synchronous by default.  Each Celery task that needs
to call async application code must create a fresh event loop — but the
naive ``asyncio.run()`` pattern is dangerous when the failure-handling
path is also async, because ``asyncio.run()`` cannot be called from a
running event loop, producing a ``RuntimeError`` at runtime.

This module provides ``run_async_in_celery``, a single helper that:

* Calls ``engine.dispose(close=True)`` before creating a new loop so that
  connections carried over from a previous loop are fully released.
* Detects (unexpected) already-running loops and falls back to a
  manually-created loop with full cleanup.
* Is completely service-agnostic — the caller passes its own ``engine``
  and ``service_name``; no globals are imported.

Usage (in any service's task file)::

    from tr_shared.celery import run_async_in_celery
    from app.core.database import engine
    from app.core.config import get_settings

    settings = get_settings()

    @celery_app.task(bind=True, max_retries=3)
    def process_something(self, entity_id: str) -> None:
        run_async_in_celery(
            _process_async(entity_id),
            engine=engine,
            service_name=settings.SERVICE_NAME,
        )
"""

import asyncio
import logging
from typing import Awaitable, TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine

T = TypeVar("T")

logger = logging.getLogger(__name__)


def run_async_in_celery(
    coro: Awaitable[T],
    *,
    engine: AsyncEngine,
    service_name: str,
) -> T:
    """Run an async coroutine inside a Celery (synchronous) worker process.

    Properly handles event loop creation in forked Celery workers so that
    database connections and other async resources work correctly.

    Args:
        coro: The async coroutine to execute.
        engine: The SQLAlchemy ``AsyncEngine`` for this service.  Its
            connection pool is disposed before creating the new event loop
            to prevent stale file-descriptor leaks across retries.
        service_name: Human-readable service identifier used in log
            messages only — not used for routing or config.

    Returns:
        Whatever the coroutine returns.

    Raises:
        Any exception raised by the coroutine.

    Note:
        Uses ``asyncio.run()`` to create a completely fresh event loop for
        each task invocation.  This ensures database connections are
        created within the correct loop context, avoiding
        "attached to a different loop" errors.

        The engine pool is disposed with ``close=True`` (closes the
        kernel-level socket) before the new loop is created, preventing
        accumulation of orphaned file descriptors.
    """
    # Dispose of the connection pool so no sockets from a previous loop
    # survive into the new one.  close=True shuts the kernel socket; the
    # pool will be recreated automatically on next use.
    try:
        engine.dispose(close=True)
    except Exception as exc:
        logger.debug(
            "Database connection pool disposal (may be expected) - service=%s, error=%s",
            service_name,
            str(exc) or "none",
        )

    try:
        asyncio.get_running_loop()
        # A running loop inside a Celery worker is unexpected.  Create a
        # new loop manually so we don't crash.
        logger.warning(
            "Running event loop detected in Celery worker — creating a new loop. "
            "service=%s",
            service_name,
            stack_info=True,
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            # Cancel any tasks that the coroutine left pending.
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as exc:
                logger.debug(
                    "Error cancelling pending tasks during event loop cleanup - service=%s, error=%s",
                    service_name,
                    str(exc),
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)
    except RuntimeError:
        # No running loop — the normal case inside a Celery worker.
        # asyncio.run() creates a fresh loop, runs the coroutine, then
        # tears the loop down cleanly.
        return asyncio.run(coro)
