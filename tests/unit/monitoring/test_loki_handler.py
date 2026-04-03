"""Tests for LokiHandler."""
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from tr_shared.monitoring.loki_handler import LokiHandler


@pytest.fixture
def handler():
    """LokiHandler with mocked background thread so no real I/O starts."""
    with patch("threading.Thread"):
        h = LokiHandler(
            url="http://loki:3100/loki/api/v1/push",
            labels={"service": "test", "environment": "test"},
            batch_size=100,
            flush_interval=3600,
        )
        yield h


class TestInit:
    def test_stores_url(self, handler):
        assert handler.url == "http://loki:3100/loki/api/v1/push"

    def test_stores_static_labels(self, handler):
        assert handler.static_labels["service"] == "test"

    def test_buffer_starts_empty(self, handler):
        assert len(handler._buffer) == 0

    def test_default_labels_is_empty_dict(self):
        with patch("threading.Thread"):
            h = LokiHandler(url="http://loki:3100")
            assert h.static_labels == {}


class TestEmit:
    def test_emit_adds_entry_to_buffer(self, handler):
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        handler.emit(record)
        assert len(handler._buffer) == 1

    def test_emit_stores_nanosecond_timestamp(self, handler):
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        handler.emit(record)
        ts_ns, _, _ = handler._buffer[0]
        assert ts_ns.isdigit()
        assert len(ts_ns) > 10  # nanosecond precision

    def test_emit_includes_level_in_labels(self, handler):
        record = logging.LogRecord("test", logging.ERROR, "", 0, "err", (), None)
        handler.emit(record)
        _, labels, _ = handler._buffer[0]
        assert labels["level"] == "error"

    def test_emit_includes_static_labels(self, handler):
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        handler.emit(record)
        _, labels, _ = handler._buffer[0]
        assert labels["service"] == "test"
        assert labels["environment"] == "test"

    def test_emit_triggers_flush_at_batch_size(self, handler):
        handler.batch_size = 3
        with patch.object(handler, "_flush") as mock_flush:
            for i in range(3):
                r = logging.LogRecord("t", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(r)
            mock_flush.assert_called()


class TestFormatRecord:
    def test_includes_message(self, handler):
        record = logging.LogRecord("t", logging.INFO, "", 0, "my message", (), None)
        result = json.loads(handler._format_record(record))
        assert result["message"] == "my message"

    def test_includes_logger_name(self, handler):
        record = logging.LogRecord("my.logger", logging.DEBUG, "", 0, "x", (), None)
        result = json.loads(handler._format_record(record))
        assert result["logger"] == "my.logger"

    def test_includes_level(self, handler):
        record = logging.LogRecord("t", logging.WARNING, "", 0, "x", (), None)
        result = json.loads(handler._format_record(record))
        assert result["level"] == "WARNING"

    def test_includes_tenant_id_when_present(self, handler):
        record = logging.LogRecord("t", logging.INFO, "", 0, "x", (), None)
        record.tenant_id = "tenant-abc"
        result = json.loads(handler._format_record(record))
        assert result["tenant_id"] == "tenant-abc"

    def test_includes_correlation_id_when_present(self, handler):
        record = logging.LogRecord("t", logging.INFO, "", 0, "x", (), None)
        record.correlation_id = "corr-123"
        result = json.loads(handler._format_record(record))
        assert result["correlation_id"] == "corr-123"


class TestFlush:
    def _make_mock_http_client(self, status_code=204):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = ""
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.post.return_value = mock_response
        return client

    def test_empty_buffer_does_not_call_http(self, handler):
        with patch("tr_shared.monitoring.loki_handler.httpx.Client") as mock_cls:
            handler._flush()
            mock_cls.assert_not_called()

    def test_flush_posts_to_loki_url(self, handler):
        record = logging.LogRecord("t", logging.INFO, "", 0, "send me", (), None)
        handler.emit(record)

        mock_client = self._make_mock_http_client()
        with patch(
            "tr_shared.monitoring.loki_handler.httpx.Client", return_value=mock_client
        ):
            handler._flush()
            mock_client.post.assert_called_once()
            assert mock_client.post.call_args[0][0] == handler.url

    def test_flush_clears_buffer(self, handler):
        record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
        handler.emit(record)

        mock_client = self._make_mock_http_client()
        with patch(
            "tr_shared.monitoring.loki_handler.httpx.Client", return_value=mock_client
        ):
            handler._flush()
        assert len(handler._buffer) == 0

    def test_flush_swallows_http_connection_error(self, handler):
        record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
        handler.emit(record)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("connect refused")
        with patch(
            "tr_shared.monitoring.loki_handler.httpx.Client", return_value=mock_client
        ):
            handler._flush()  # Must not raise

    def test_flush_warns_on_loki_4xx(self, handler):
        record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
        handler.emit(record)

        mock_client = self._make_mock_http_client(status_code=400)
        with patch(
            "tr_shared.monitoring.loki_handler.httpx.Client", return_value=mock_client
        ):
            handler._flush()  # Should not raise


class TestClose:
    def test_close_calls_flush(self, handler):
        with patch.object(handler, "_flush") as mock_flush:
            handler.close()
            mock_flush.assert_called_once()
