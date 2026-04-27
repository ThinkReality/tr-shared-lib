"""
Persistent worker event loop for Celery tasks.

Celery workers are synchronous. Tasks that need to call async code must
run that code on an asyncio loop. The naive ``asyncio.run(coro)`` pattern
creates and destroys a fresh loop on every task — which silently breaks
any async resource (httpx connection pool, SQLAlchemy AsyncEngine, Redis
async client) whose internal state is bound to the loop. The next task
finds those resources still cached but pointing at a closed loop, and
raises ``RuntimeError: Event loop is closed``.

This module provides a single persistent event loop per worker process.
Every task runs on that one loop. Long-lived async resources stay healthy
across tasks. This is the canonical Celery + asyncio integration pattern.

Wiring (each service's ``app/celery_app.py``)::

    from celery.signals import worker_process_shutdown
    from tr_shared.celery import shutdown_worker_loop

    @worker_process_shutdown.connect
    def _close_loop(**_kwargs):
        shutdown_worker_loop()

Usage (in any task)::

    from tr_shared.celery import run_async_in_celery

    @celery_app.task(bind=True)
    def my_task(self, entity_id: str):
        return run_async_in_celery(_my_async_impl(entity_id))
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Module-global loop — one per worker process. Celery's ``solo`` and
# ``prefork`` pools each give a fresh process per worker, so the global
# is per-worker by virtue of process boundaries.
_worker_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_or_create_worker_loop() -> asyncio.AbstractEventLoop:
    """Return this worker's persistent event loop, creating it if needed.

    Thread-safe — Celery's solo/prefork pools are single-threaded per
    process, but the lock guards against re-entry from signal handlers.
    """
    global _worker_loop
    with _loop_lock:
        if _worker_loop is None or _worker_loop.is_closed():
            _worker_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_worker_loop)
        return _worker_loop


def run_async_in_celery(
    coro: Awaitable[T],
    *,
    engine: AsyncEngine | None = None,
    service_name: str | None = None,
) -> T:
    """Run an async coroutine on this worker's persistent event loop.

    All tasks in a worker process share ONE event loop. This keeps async
    resource pools (httpx, SQLAlchemy, Redis) alive across tasks instead
    of having them bind+die on every invocation.

    Args:
        coro: The async coroutine to execute.
        engine: Deprecated — kept for backward compatibility. With a
            persistent loop, per-task ``engine.dispose()`` is harmful
            (it drains the connection pool every task) and unnecessary
            (the pool stays bound to the same loop). Pass ``None`` or
            simply omit. Kept to avoid breaking existing callers.
        service_name: Deprecated — kept for backward compatibility and
            no longer used in logging. Will be removed in a future
            major bump once all callers stop passing it.

    Returns:
        Whatever the coroutine returns.

    Raises:
        Any exception raised by the coroutine.
    """
    # Keep backward-compat parameters silent. Callers can drop them at
    # their convenience.
    _ = engine, service_name
    loop = _get_or_create_worker_loop()
    return loop.run_until_complete(coro)


def shutdown_worker_loop(**_kwargs: Any) -> None:
    """Close the persistent worker event loop on worker shutdown.

    Wire this to Celery's ``worker_process_shutdown`` signal. Idempotent —
    safe to call multiple times. Kwargs are accepted so this can be used
    directly as a signal handler without a wrapper.
    """
    global _worker_loop
    with _loop_lock:
        if _worker_loop is None or _worker_loop.is_closed():
            _worker_loop = None
            return
        loop = _worker_loop
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True),
                )
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            logger.debug("worker_loop_pending_task_cleanup_error: %s", exc)
        finally:
            try:
                loop.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("worker_loop_close_error: %s", exc)
            _worker_loop = None
