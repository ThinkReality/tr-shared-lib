"""Tests for the persistent worker event loop.

The contract this file pins is the *reason the module exists*: one event loop
per worker process, shared by every task, torn down once at worker shutdown.

An earlier version of this suite tested the opposite design — a fresh
``asyncio.run()`` per task with ``engine.dispose(close=True)`` in front of it.
That design was replaced because it drained the connection pool on every task
and left async resources bound to a closed loop. The tests were not replaced
with it, so they asserted behaviour the module had deliberately dropped.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from tr_shared.celery import async_runner
from tr_shared.celery.async_runner import run_async_in_celery, shutdown_worker_loop


@pytest.fixture(autouse=True)
def _fresh_worker_loop():
    """The loop is a module global. Without this, one test's loop leaks into
    the next and loop-identity assertions become meaningless."""
    shutdown_worker_loop()
    yield
    shutdown_worker_loop()


async def _returns(value):
    return value


async def _raises():
    raise ValueError("boom")


class TestRunAsyncInCelery:
    def test_returns_coroutine_result(self):
        assert run_async_in_celery(_returns(42)) == 42

    def test_returns_none_result(self):
        assert run_async_in_celery(_returns(None)) is None

    def test_propagates_exception_from_coroutine(self):
        with pytest.raises(ValueError, match="boom"):
            run_async_in_celery(_raises())

    def test_the_same_loop_serves_every_call(self):
        """The whole point of the module. A per-task loop would make each call
        see a different one, and every pooled async resource would die with it."""
        run_async_in_celery(_returns(1))
        first = async_runner._worker_loop

        run_async_in_celery(_returns(2))

        assert async_runner._worker_loop is first
        assert not first.is_closed()

    def test_a_resource_bound_to_the_loop_survives_the_next_call(self):
        """Behavioural form of the above. A Future is bound to the loop that
        created it, which is what makes it a valid probe — ``asyncio.Event``,
        ``Lock`` and ``Queue`` stopped binding at construction in 3.10 and would
        pass here even with a fresh loop per task.

        Under the old per-task-loop design the second call raised
        ``RuntimeError: Event loop is closed`` — the exact failure the
        persistent loop exists to prevent.
        """

        async def make_future():
            return asyncio.get_running_loop().create_future()

        future = run_async_in_celery(make_future())

        async def resolve_it():
            # Scheduled, not set inline: an already-resolved Future is awaited
            # without ever touching a loop, so setting the result first would
            # make this pass on any loop at all.
            asyncio.get_running_loop().call_soon(future.set_result, "resolved")
            return await future

        assert run_async_in_celery(resolve_it()) == "resolved"


class TestDeprecatedParameters:
    def test_engine_is_accepted_and_never_disposed(self):
        """``engine`` is kept only so existing callers keep working. Disposing
        it per task is exactly the behaviour this module removed: it drains the
        pool every task while the loop it is bound to stays alive."""
        engine = MagicMock()

        assert run_async_in_celery(_returns("ok"), engine=engine) == "ok"

        engine.dispose.assert_not_called()

    def test_service_name_is_accepted(self):
        assert run_async_in_celery(_returns("ok"), service_name="svc") == "ok"


class TestShutdownWorkerLoop:
    def test_closes_the_loop_and_clears_the_global(self):
        run_async_in_celery(_returns(1))
        loop = async_runner._worker_loop

        shutdown_worker_loop()

        assert loop.is_closed()
        assert async_runner._worker_loop is None

    def test_is_idempotent(self):
        run_async_in_celery(_returns(1))

        shutdown_worker_loop()
        shutdown_worker_loop()

        assert async_runner._worker_loop is None

    def test_is_safe_before_any_task_has_run(self):
        shutdown_worker_loop()

        assert async_runner._worker_loop is None

    def test_accepts_signal_kwargs(self):
        """Wired directly to Celery's ``worker_process_shutdown``, which sends
        sender/pid/exitcode. A bare ``def f()`` here would raise at shutdown."""
        run_async_in_celery(_returns(1))

        shutdown_worker_loop(sender=object(), pid=123, exitcode=0)

        assert async_runner._worker_loop is None

    def test_cancels_tasks_still_pending(self):
        """A task left running by one Celery task must not keep the process
        alive or vanish silently — shutdown cancels it."""

        async def spawn_never_finishing_task():
            return asyncio.ensure_future(asyncio.sleep(3600))

        pending = run_async_in_celery(spawn_never_finishing_task())
        assert not pending.done()

        shutdown_worker_loop()

        assert pending.cancelled()

    def test_a_later_call_gets_a_fresh_working_loop(self):
        run_async_in_celery(_returns(1))
        first = async_runner._worker_loop
        shutdown_worker_loop()

        assert run_async_in_celery(_returns(2)) == 2

        assert async_runner._worker_loop is not first
        assert not async_runner._worker_loop.is_closed()
