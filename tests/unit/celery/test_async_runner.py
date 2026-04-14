"""Tests for run_async_in_celery helper.

TDD suite covering four scenarios:
(a) happy path — coroutine runs and result is returned
(b) running-loop detection branch — falls back to manually-created loop
(c) engine.dispose(close=True) is called before the loop is created
(d) pending tasks are cancelled during fallback-loop cleanup
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from tr_shared.celery.async_runner import run_async_in_celery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> MagicMock:
    """Return a mock AsyncEngine whose dispose() can be inspected."""
    engine = MagicMock()
    engine.dispose = MagicMock()
    return engine


async def _returns_value(value):
    return value


async def _raises(exc_type):
    raise exc_type("boom")


# ---------------------------------------------------------------------------
# (a) Happy path — no running loop, coroutine completes normally
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_coroutine_result(self):
        engine = _make_engine()

        result = run_async_in_celery(
            _returns_value(42),
            engine=engine,
            service_name="test-svc",
        )

        assert result == 42

    def test_propagates_exception_from_coroutine(self):
        engine = _make_engine()

        with pytest.raises(ValueError, match="boom"):
            run_async_in_celery(
                _raises(ValueError),
                engine=engine,
                service_name="test-svc",
            )

    def test_works_with_none_return(self):
        engine = _make_engine()

        async def returns_none():
            return None

        result = run_async_in_celery(returns_none(), engine=engine, service_name="svc")
        assert result is None


# ---------------------------------------------------------------------------
# (c) engine.dispose(close=True) is called before loop creation
# ---------------------------------------------------------------------------


class TestEngineDispose:
    def test_dispose_called_with_close_true(self):
        engine = _make_engine()

        run_async_in_celery(_returns_value("ok"), engine=engine, service_name="svc")

        engine.dispose.assert_called_once_with(close=True)

    def test_dispose_exception_does_not_abort_run(self):
        """A broken dispose() must not prevent the coroutine from running."""
        engine = _make_engine()
        engine.dispose.side_effect = RuntimeError("pool already closed")

        result = run_async_in_celery(_returns_value("still ok"), engine=engine, service_name="svc")

        assert result == "still ok"

    def test_dispose_called_before_asyncio_run(self):
        """dispose() must precede asyncio.run() in the call order."""
        engine = _make_engine()
        call_order: list[str] = []

        engine.dispose.side_effect = lambda **_: call_order.append("dispose")

        original_asyncio_run = asyncio.run

        def tracking_run(coro, **kwargs):
            call_order.append("asyncio.run")
            return original_asyncio_run(coro, **kwargs)

        with patch("tr_shared.celery.async_runner.asyncio.run", side_effect=tracking_run):
            run_async_in_celery(_returns_value(1), engine=engine, service_name="svc")

        assert call_order == ["dispose", "asyncio.run"]


# ---------------------------------------------------------------------------
# (b) Running-loop detection — fallback to manually-created loop
# ---------------------------------------------------------------------------


class TestRunningLoopFallback:
    def test_fallback_loop_used_when_running_loop_detected(self):
        """When a running loop exists, the helper must still execute the
        coroutine and return the result (not raise RuntimeError)."""
        engine = _make_engine()

        # Simulate a running loop by patching get_running_loop to succeed
        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = "from-fallback"
        mock_loop.is_closed.return_value = False

        # all_tasks() must return an empty iterable so cleanup logic is a no-op
        with (
            patch("tr_shared.celery.async_runner.asyncio.get_running_loop"),  # doesn't raise → running loop detected
            patch("tr_shared.celery.async_runner.asyncio.new_event_loop", return_value=mock_loop),
            patch("tr_shared.celery.async_runner.asyncio.set_event_loop"),
            patch("tr_shared.celery.async_runner.asyncio.all_tasks", return_value=[]),
        ):
            result = run_async_in_celery(
                _returns_value("from-fallback"),
                engine=engine,
                service_name="test-svc",
            )

        assert result == "from-fallback"

    def test_new_event_loop_created_on_running_loop_detection(self):
        engine = _make_engine()

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = None

        with (
            patch("tr_shared.celery.async_runner.asyncio.get_running_loop"),
            patch("tr_shared.celery.async_runner.asyncio.new_event_loop", return_value=mock_loop) as new_loop_mock,
            patch("tr_shared.celery.async_runner.asyncio.set_event_loop"),
            patch("tr_shared.celery.async_runner.asyncio.all_tasks", return_value=[]),
        ):
            run_async_in_celery(_returns_value(None), engine=engine, service_name="svc")

        new_loop_mock.assert_called_once()

    def test_event_loop_closed_after_fallback(self):
        engine = _make_engine()

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = None

        with (
            patch("tr_shared.celery.async_runner.asyncio.get_running_loop"),
            patch("tr_shared.celery.async_runner.asyncio.new_event_loop", return_value=mock_loop),
            patch("tr_shared.celery.async_runner.asyncio.set_event_loop"),
            patch("tr_shared.celery.async_runner.asyncio.all_tasks", return_value=[]),
        ):
            run_async_in_celery(_returns_value(None), engine=engine, service_name="svc")

        mock_loop.close.assert_called_once()


# ---------------------------------------------------------------------------
# (d) Pending tasks are cancelled during fallback-loop cleanup
# ---------------------------------------------------------------------------


class TestPendingTaskCancellation:
    def test_pending_tasks_cancelled_during_cleanup(self):
        engine = _make_engine()

        # Create two fake pending asyncio.Tasks
        task1 = MagicMock()
        task1.done.return_value = False
        task1.cancel = MagicMock()

        task2 = MagicMock()
        task2.done.return_value = False
        task2.cancel = MagicMock()

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = None

        with (
            patch("tr_shared.celery.async_runner.asyncio.get_running_loop"),
            patch("tr_shared.celery.async_runner.asyncio.new_event_loop", return_value=mock_loop),
            patch("tr_shared.celery.async_runner.asyncio.set_event_loop"),
            patch("tr_shared.celery.async_runner.asyncio.all_tasks", return_value=[task1, task2]),
            patch("tr_shared.celery.async_runner.asyncio.gather", return_value=AsyncMock()),
        ):
            run_async_in_celery(_returns_value(None), engine=engine, service_name="svc")

        task1.cancel.assert_called_once()
        task2.cancel.assert_called_once()

    def test_already_done_tasks_not_cancelled(self):
        """Tasks already done must not be cancelled — only pending ones."""
        engine = _make_engine()

        done_task = MagicMock()
        done_task.done.return_value = True
        done_task.cancel = MagicMock()

        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = None

        with (
            patch("tr_shared.celery.async_runner.asyncio.get_running_loop"),
            patch("tr_shared.celery.async_runner.asyncio.new_event_loop", return_value=mock_loop),
            patch("tr_shared.celery.async_runner.asyncio.set_event_loop"),
            patch("tr_shared.celery.async_runner.asyncio.all_tasks", return_value=[done_task]),
            patch("tr_shared.celery.async_runner.asyncio.gather"),
        ):
            run_async_in_celery(_returns_value(None), engine=engine, service_name="svc")

        done_task.cancel.assert_not_called()
