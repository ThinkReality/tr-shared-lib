"""Tests for no-op monitoring adapters."""
import logging

from tr_shared.monitoring.adapters.noop import (
    NoopLogAdapter,
    NoopMetricsAdapter,
    NoopTraceAdapter,
)


class TestNoopMetricsAdapter:
    def test_create_metric_reader_returns_none(self):
        assert NoopMetricsAdapter().create_metric_reader() is None

    def test_start_server_returns_none(self):
        assert NoopMetricsAdapter().start_server(port=9090, service_name="svc") is None

    def test_create_metrics_router_returns_none(self):
        assert NoopMetricsAdapter().create_metrics_router() is None


class TestNoopLogAdapter:
    def test_create_handler_returns_null_handler(self):
        handler = NoopLogAdapter().create_handler("svc", {"env": "test"})
        assert isinstance(handler, logging.NullHandler)

    def test_create_handler_works_with_empty_labels(self):
        handler = NoopLogAdapter().create_handler("svc", {})
        assert isinstance(handler, logging.NullHandler)


class TestNoopTraceAdapter:
    def test_create_span_exporter_returns_none(self):
        assert NoopTraceAdapter().create_span_exporter() is None
