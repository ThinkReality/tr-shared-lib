"""G6d — ``.delay()``/``.apply_async()`` must never run inside the caller's open
transaction.

Under Celery eager mode (``task_always_eager=True``, the fleet's test-time execution
mode), ``.delay()`` runs the task body synchronously in the caller's own stack. If the
caller still has an open, uncommitted transaction on a *tracked* session, the eager task
can see rows a real worker — a separate process, reading only committed data — never
would. A test that seeds data without committing and then dispatches a task can pass for
the wrong reason: the eager run "sees" the row, production never would.

This does not scan for the bug statically (undecidable — which session a task will see
depends on runtime wiring); it fires when the bug actually happens, by connecting to
Celery's own tracer.

The violation is recorded, not raised, inside the signal handler: Celery's dispatcher
(``celery.utils.dispatch.signal.Signal.send``) catches every receiver's exceptions and
only logs them — a raise there never reaches the caller. ``track_session``'s own
``__exit__`` is outside that boundary, so it re-raises there instead.

Usage — opt a session in around the dispatch you want checked::

    from tr_shared.testing.transaction_guard import install_transaction_guard, track_session

    install_transaction_guard(celery_app)  # once, e.g. session-scoped in conftest.py

    async with session.begin():
        session.add(row)
        with track_session(session):
            my_task.delay(...)   # raises AssertionError — row not committed yet
        await session.commit()
        with track_session(session):
            my_task.delay(...)   # fine — no open transaction
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from celery import Celery
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["install_transaction_guard", "track_session"]

_active_session: ContextVar[Any] = ContextVar("_active_session", default=None)
_violation: ContextVar[str | None] = ContextVar("_violation", default=None)


@contextmanager
def track_session(session: "AsyncSession") -> Iterator[None]:
    """Make ``session`` visible to the guard for the duration of the block."""
    session_token = _active_session.set(session)
    violation_token = _violation.set(None)
    try:
        yield
    finally:
        _active_session.reset(session_token)
        violation = _violation.get()
        _violation.reset(violation_token)
        if violation:
            raise AssertionError(violation)


def _check_no_open_transaction(sender: Any = None, task: Any = None, **_: Any) -> None:
    app = getattr(task, "app", None)
    if app is None or not app.conf.task_always_eager:
        return
    session = _active_session.get()
    if session is None or not session.in_transaction():
        return
    _violation.set(
        f"{getattr(task, 'name', task)!r} was dispatched via .delay()/.apply_async() "
        "while the tracked session still has an open, uncommitted transaction (G6d). "
        "Under eager mode this task now runs synchronously inside that transaction and "
        "can see uncommitted rows a real worker never would — commit (or roll back) "
        "before dispatching, or stop tracking this session with track_session() if the "
        "task intentionally shares it."
    )


def install_transaction_guard(celery_app: "Celery") -> None:
    """Connect the guard to ``task_prerun`` — the signal Celery's tracer fires for
    BOTH eager and real execution (``before_task_publish`` does not fire in eager
    mode: ``apply_async()`` short-circuits straight to ``apply()`` and skips the
    publish step entirely). Idempotent per process — connecting twice is harmless,
    Celery signals dedupe identical receivers.
    """
    from celery.signals import task_prerun

    task_prerun.connect(_check_no_open_transaction, sender=None, weak=False)
