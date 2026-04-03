"""Shared structured logging configuration."""

from tr_shared.logging.setup import bind_correlation_id, configure_logging, get_logger

__all__ = ["bind_correlation_id", "configure_logging", "get_logger"]
