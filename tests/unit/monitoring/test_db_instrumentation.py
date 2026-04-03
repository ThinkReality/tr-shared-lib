"""Tests for setup_db_instrumentation."""
import time
from unittest.mock import MagicMock, patch

import pytest


class TestExtractOperationType:
    def test_select(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type("SELECT * FROM t") == "SELECT"

    def test_insert(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type("INSERT INTO t VALUES (1)") == "INSERT"

    def test_update(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type("UPDATE t SET x=1") == "UPDATE"

    def test_delete(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type("DELETE FROM t WHERE id=1") == "DELETE"

    def test_other_ddl(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type("VACUUM t") == "OTHER"

    def test_empty_string(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type("") == "UNKNOWN"

    def test_none(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type(None) == "UNKNOWN"

    def test_case_insensitive(self):
        from tr_shared.monitoring.db_instrumentation import _extract_operation_type
        assert _extract_operation_type("select 1") == "SELECT"


class TestSetupDbInstrumentation:
    @pytest.fixture
    def mock_engine(self):
        engine = MagicMock()
        engine.sync_engine = MagicMock()
        return engine

    @pytest.fixture
    def captured(self, mock_engine):
        """Captures registered event handlers and instrument mocks."""
        handlers = {}

        def fake_listens_for(target, event_name):
            def decorator(fn):
                handlers[event_name] = fn
                return fn
            return decorator

        histogram = MagicMock()
        counter = MagicMock()
        meter = MagicMock()
        meter.create_histogram.return_value = histogram
        meter.create_counter.return_value = counter

        with patch("tr_shared.monitoring.db_instrumentation.event") as mock_event, \
             patch("tr_shared.monitoring.db_instrumentation.metrics") as mock_metrics:
            mock_event.listens_for.side_effect = fake_listens_for
            mock_metrics.get_meter.return_value = meter
            from tr_shared.monitoring.db_instrumentation import setup_db_instrumentation
            setup_db_instrumentation(engine=mock_engine)

        return {"handlers": handlers, "histogram": histogram, "counter": counter}

    def test_registers_before_and_after_listeners(self, captured):
        assert "before_cursor_execute" in captured["handlers"]
        assert "after_cursor_execute" in captured["handlers"]

    def test_before_handler_sets_start_time(self, captured):
        ctx = MagicMock()
        before = time.perf_counter()
        captured["handlers"]["before_cursor_execute"](None, None, "SELECT 1", None, ctx, False)
        after = time.perf_counter()
        assert before <= ctx._query_start_time <= after

    def test_after_handler_records_duration_and_counter(self, captured):
        ctx = MagicMock()
        ctx._query_start_time = time.perf_counter() - 0.05  # 50 ms ago

        captured["handlers"]["after_cursor_execute"](None, None, "SELECT 1", None, ctx, False)

        captured["histogram"].record.assert_called_once()
        duration, labels = captured["histogram"].record.call_args.args
        assert duration >= 0.04
        assert labels == {"db.system": "postgresql", "db.operation": "SELECT"}
        captured["counter"].add.assert_called_once_with(
            1, {"db.system": "postgresql", "db.operation": "SELECT"}
        )

    def test_after_handler_skips_when_no_start_time(self, captured):
        ctx = MagicMock(spec=[])  # no _query_start_time attribute
        captured["handlers"]["after_cursor_execute"](None, None, "SELECT 1", None, ctx, False)
        captured["histogram"].record.assert_not_called()
        captured["counter"].add.assert_not_called()
