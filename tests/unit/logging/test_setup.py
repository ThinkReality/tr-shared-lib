"""Tests for configure_logging and get_logger."""

import logging
from unittest.mock import MagicMock


from tr_shared.logging.setup import (
    _mask_sensitive_fields,
    configure_logging,
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
