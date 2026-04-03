"""Tests for PrometheusMetricsAdapter and OtlpTraceAdapter."""
from unittest.mock import MagicMock, patch

import pytest

from tr_shared.monitoring.adapters.prometheus_metrics import PrometheusMetricsAdapter
from tr_shared.monitoring.adapters.otlp_trace import OtlpTraceAdapter


class TestPrometheusMetricsAdapter:
    def test_create_metric_reader_returns_reader(self):
        adapter = PrometheusMetricsAdapter()
        reader = adapter.create_metric_reader()
        assert reader is not None

    def test_start_server_returns_none_for_zero_port(self):
        adapter = PrometheusMetricsAdapter()
        assert adapter.start_server(port=0, service_name="svc") is None

    def test_start_server_returns_none_for_negative_port(self):
        adapter = PrometheusMetricsAdapter()
        assert adapter.start_server(port=-1, service_name="svc") is None

    def test_start_server_calls_underlying_helper_for_positive_port(self):
        adapter = PrometheusMetricsAdapter()
        with patch(
            "tr_shared.monitoring.prometheus_endpoint.start_http_server"
        ) as mock_start:
            mock_start.return_value = MagicMock()
            adapter.start_server(port=9090, service_name="svc")
            mock_start.assert_called_once()

    def test_create_metrics_router_returns_fastapi_router(self):
        from fastapi import APIRouter

        adapter = PrometheusMetricsAdapter()
        router = adapter.create_metrics_router()
        assert isinstance(router, APIRouter)


class TestOtlpTraceAdapter:
    def test_empty_endpoint_returns_none(self):
        assert OtlpTraceAdapter(endpoint="").create_span_exporter() is None

    def test_default_endpoint_returns_none(self):
        assert OtlpTraceAdapter().create_span_exporter() is None

    def test_stores_endpoint(self):
        adapter = OtlpTraceAdapter(endpoint="http://otel:4317")
        assert adapter.endpoint == "http://otel:4317"

    def test_with_endpoint_returns_exporter(self):
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError:
            pytest.skip("opentelemetry-exporter-otlp-proto-grpc not installed")

        adapter = OtlpTraceAdapter(endpoint="http://tempo:4317")
        exporter = adapter.create_span_exporter()
        assert exporter is not None
        assert isinstance(exporter, OTLPSpanExporter)
