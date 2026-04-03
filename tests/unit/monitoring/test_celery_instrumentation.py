"""Tests for setup_celery_instrumentation."""
from unittest.mock import MagicMock, patch

import pytest


class TestSetupCeleryInstrumentation:
    @pytest.fixture(autouse=True)
    def reset_guard(self):
        """Reset idempotency guard so each test starts clean."""
        import tr_shared.monitoring.celery_instrumentation as mod
        mod._instrumented = False
        yield
        mod._instrumented = False

    def _call_with_mocks(self):
        """Invoke setup_celery_instrumentation with all external calls mocked.

        Returns a dict with captured signal handlers and instrument mocks.
        """
        histogram = MagicMock()
        counter = MagicMock()
        up_down = MagicMock()
        meter = MagicMock()
        meter.create_histogram.return_value = histogram
        meter.create_counter.return_value = counter
        meter.create_up_down_counter.return_value = up_down

        prerun_handlers: list = []
        failure_handlers: list = []
        postrun_handlers: list = []

        with patch("tr_shared.monitoring.celery_instrumentation.task_prerun") as p, \
             patch("tr_shared.monitoring.celery_instrumentation.task_failure") as f, \
             patch("tr_shared.monitoring.celery_instrumentation.task_postrun") as q, \
             patch("tr_shared.monitoring.celery_instrumentation.metrics") as mock_metrics:
            mock_metrics.get_meter.return_value = meter
            p.connect.side_effect = lambda fn: prerun_handlers.append(fn)
            f.connect.side_effect = lambda fn: failure_handlers.append(fn)
            q.connect.side_effect = lambda fn: postrun_handlers.append(fn)

            from tr_shared.monitoring.celery_instrumentation import setup_celery_instrumentation
            setup_celery_instrumentation()

        return {
            "histogram": histogram,
            "counter": counter,
            "up_down": up_down,
            "prerun": prerun_handlers,
            "failure": failure_handlers,
            "postrun": postrun_handlers,
        }

    def test_connects_three_signals(self):
        r = self._call_with_mocks()
        assert len(r["prerun"]) == 1
        assert len(r["failure"]) == 1
        assert len(r["postrun"]) == 1

    def test_idempotent_second_call_skipped(self):
        """A second call should not register additional handlers."""
        self._call_with_mocks()          # first call registers
        r2 = self._call_with_mocks()     # second call is no-op (guard is set)
        assert len(r2["prerun"]) == 0
        assert len(r2["failure"]) == 0
        assert len(r2["postrun"]) == 0

    def test_successful_task_lifecycle(self):
        """prerun + postrun: active +1/-1, counter success, duration recorded."""
        r = self._call_with_mocks()
        task = MagicMock()
        task.name = "my_task"

        r["prerun"][0](task_id="abc", task=task)
        r["postrun"][0](task_id="abc", task=task)

        r["up_down"].add.assert_any_call(1, {"task.name": "my_task"})
        r["up_down"].add.assert_any_call(-1, {"task.name": "my_task"})
        r["counter"].add.assert_called_once_with(
            1, {"task.name": "my_task", "status": "success"}
        )
        r["histogram"].record.assert_called_once()
        duration = r["histogram"].record.call_args.args[0]
        assert duration >= 0

    def test_failed_task_lifecycle(self):
        """failure signal causes postrun counter to use status=failure."""
        r = self._call_with_mocks()
        task = MagicMock()
        task.name = "bad_task"

        r["prerun"][0](task_id="xyz", task=task)
        r["failure"][0](task_id="xyz", task=task)
        r["postrun"][0](task_id="xyz", task=task)

        r["counter"].add.assert_called_once_with(
            1, {"task.name": "bad_task", "status": "failure"}
        )

    def test_postrun_without_prerun_does_not_raise(self):
        """Missing start time (e.g. TTL eviction) should not crash."""
        r = self._call_with_mocks()
        task = MagicMock()
        task.name = "orphan_task"

        # postrun fires without a matching prerun
        r["postrun"][0](task_id="no-start", task=task)

        r["histogram"].record.assert_not_called()
        r["counter"].add.assert_called_once()   # counter still recorded
