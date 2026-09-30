"""Tests for configure_logging and get_logger."""

import json
import logging
from unittest.mock import MagicMock

import structlog

from tr_shared.logging.setup import (
    _mask_sensitive_fields,
    bind_correlation_id,
    configure_logging,
    get_correlation_id,
    get_logger,
)


class TestMaskSensitiveFields:
    def _mask(self, event: dict) -> dict:
        return _mask_sensitive_fields(None, "info", event)

    def test_redacts_known_and_widened_field_names(self):
        for field in (
            "token",
            "secret",
            "password",
            "passwd",
            "pwd",
            "api_key",
            "apikey",
            "x-api-key",
            "authorization",
            "auth",
            "credential",
            "private_key",
            "database_url",
            "redis_url",
        ):
            out = self._mask({field: "supersecretvalue"})
            assert out[field] == "[REDACTED]", f"{field} not redacted"

    def test_full_redaction_not_partial(self):
        out = self._mask({"password": "abcdefghij"})
        assert out["password"] == "[REDACTED]"
        assert "abc" not in out["password"]

    def test_short_secret_still_fully_redacted(self):
        assert self._mask({"token": "ab"})["token"] == "[REDACTED]"

    def test_non_sensitive_fields_untouched(self):
        out = self._mask({"tenant_id": "t-1", "event": "created", "count": 5})
        assert out == {"tenant_id": "t-1", "event": "created", "count": 5}

    def test_non_str_and_empty_values_untouched(self):
        out = self._mask({"password": "", "secret_count": 3})
        assert out["password"] == ""
        assert out["secret_count"] == 3


class TestGetLogger:
    def test_returns_structlog_logger(self):
        logger = get_logger("test.module")
        # structlog returns a lazy proxy, not a stdlib Logger
        assert not isinstance(logger, logging.Logger)
        assert callable(getattr(logger, "info", None))
        assert callable(getattr(logger, "debug", None))
        assert callable(getattr(logger, "warning", None))
        assert callable(getattr(logger, "error", None))


class TestConfigureLogging:
    def test_text_format_adds_console_renderer(self):
        """configure_logging with text format should not raise."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            root.handlers.clear()
            configure_logging(log_level="INFO", log_format="text")
            assert len(root.handlers) == 1
        finally:
            root.handlers.clear()
            root.handlers.extend(original_handlers)

    def test_json_format_adds_json_renderer(self):
        """configure_logging with json format should not raise."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            root.handlers.clear()
            configure_logging(log_level="INFO", log_format="json")
            assert len(root.handlers) == 1
        finally:
            root.handlers.clear()
            root.handlers.extend(original_handlers)

    def test_sets_root_log_level(self):
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        try:
            root.handlers.clear()
            configure_logging(log_level="DEBUG", log_format="text")
            assert root.level == logging.DEBUG
        finally:
            root.handlers.clear()
            root.handlers.extend(original_handlers)
            root.setLevel(original_level)

    def test_skips_handler_setup_when_handlers_exist(self):
        """configure_logging must not add a second handler if root already has one."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        sentinel = MagicMock()
        try:
            root.handlers.clear()
            root.handlers.append(sentinel)
            configure_logging(log_level="INFO", log_format="text")
            assert len(root.handlers) == 1
            assert root.handlers[0] is sentinel
        finally:
            root.handlers.clear()
            root.handlers.extend(original_handlers)


class TestExcInfoRendering:
    def test_json_format_renders_traceback_on_exc_info(self, capsys):
        """exc_info=True in JSON mode must render a real traceback, not a
        literal boolean. Proven empirically: current setup.py drops it."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            root.handlers.clear()
            structlog.reset_defaults()
            configure_logging(log_level="INFO", log_format="json")
            logger = get_logger("test.exc_info")
            try:
                raise ValueError("boom")
            except ValueError:
                logger.error("failed", exc_info=True)

            captured = capsys.readouterr()
            payload = json.loads(captured.out.strip().splitlines()[-1])
            assert "Traceback" in payload.get("exception", ""), (
                f"expected rendered traceback in 'exception' field, got: {payload}"
            )
            assert "ValueError" in payload.get("exception", "")
        finally:
            root.handlers.clear()
            root.handlers.extend(original_handlers)
            structlog.reset_defaults()

    def test_text_format_still_uses_console_renderer(self, capsys):
        """dev/text output must keep rendering via ConsoleRenderer, unaffected
        by the JSON-only exc_info fix."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            root.handlers.clear()
            structlog.reset_defaults()
            configure_logging(log_level="INFO", log_format="text")
            logger = get_logger("test.exc_info_text")
            try:
                raise ValueError("boom")
            except ValueError:
                logger.error("failed", exc_info=True)

            captured = capsys.readouterr()
            assert "Traceback" in captured.out
            assert "ValueError" in captured.out
        finally:
            root.handlers.clear()
            root.handlers.extend(original_handlers)
            structlog.reset_defaults()


class TestGetCorrelationId:
    def setup_method(self):
        structlog.contextvars.clear_contextvars()

    def teardown_method(self):
        structlog.contextvars.clear_contextvars()

    def test_none_when_nothing_is_bound(self):
        assert get_correlation_id() is None

    def test_returns_what_bind_correlation_id_bound(self):
        bind_correlation_id("corr-123")
        assert get_correlation_id() == "corr-123"

    def test_is_exported_from_the_package(self):
        from tr_shared.logging import get_correlation_id as exported

        assert exported is get_correlation_id


class TestStdlibExtraFields:
    def _emit(self, capsys, **extra) -> dict:
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        try:
            root.handlers.clear()
            structlog.reset_defaults()
            configure_logging(log_level="INFO", log_format="json")
            logging.getLogger("test.stdlib_extra").info("something happened", extra=extra)
            return json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        finally:
            root.handlers.clear()
            root.handlers.extend(original_handlers)
            root.setLevel(original_level)

    def test_fields_passed_as_extra_reach_the_output(self, capsys):
        payload = self._emit(capsys, duration_ms=12.5, status_code=201)

        assert payload["event"] == "something happened"
        assert payload["duration_ms"] == 12.5
        assert payload["status_code"] == 201

    def test_an_extra_named_event_never_replaces_the_message(self, capsys):
        payload = self._emit(capsys, event="template.created", template_id="t-1")

        assert payload["event"] == "something happened"
        assert payload["extra_event"] == "template.created"
        assert payload["template_id"] == "t-1"

    def test_an_extra_event_equal_to_the_message_adds_nothing(self, capsys):
        payload = self._emit(capsys, event="something happened")

        assert payload["event"] == "something happened"
        assert "extra_event" not in payload

    def test_sensitive_extra_fields_are_still_redacted(self, capsys):
        payload = self._emit(capsys, api_key="supersecretvalue")

        assert payload["api_key"] == "[REDACTED]"
