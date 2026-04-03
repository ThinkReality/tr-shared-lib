"""Tests for configure_logging and get_logger."""

import logging
from unittest.mock import MagicMock, patch

import structlog

from tr_shared.logging.setup import configure_logging, get_logger


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
