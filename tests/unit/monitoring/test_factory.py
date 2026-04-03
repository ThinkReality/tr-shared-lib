"""Tests for MonitoringProviderFactory."""

import pytest
from unittest.mock import MagicMock, patch

from tr_shared.monitoring.factory import (
    LogProvider,
    MetricsProvider,
    MonitoringProviderFactory,
    TraceProvider,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_metrics_provider_prometheus_value(self):
        assert MetricsProvider.PROMETHEUS == "prometheus"

    def test_metrics_provider_noop_value(self):
        assert MetricsProvider.NOOP == "noop"

    def test_log_provider_loki_value(self):
        assert LogProvider.LOKI == "loki"

    def test_log_provider_noop_value(self):
        assert LogProvider.NOOP == "noop"

    def test_trace_provider_otlp_value(self):
        assert TraceProvider.OTLP == "otlp"

    def test_trace_provider_noop_value(self):
        assert TraceProvider.NOOP == "noop"


# ---------------------------------------------------------------------------
# create_metrics_provider
# ---------------------------------------------------------------------------

class TestCreateMetricsProvider:
    def test_prometheus_returns_prometheus_adapter(self):
        from tr_shared.monitoring.adapters.prometheus_metrics import (
            PrometheusMetricsAdapter,
        )
        result = MonitoringProviderFactory.create_metrics_provider("prometheus")
        assert isinstance(result, PrometheusMetricsAdapter)

    def test_noop_returns_noop_adapter(self):
        from tr_shared.monitoring.adapters.noop import NoopMetricsAdapter
        result = MonitoringProviderFactory.create_metrics_provider("noop")
        assert isinstance(result, NoopMetricsAdapter)

    def test_invalid_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported metrics provider"):
            MonitoringProviderFactory.create_metrics_provider("invalid")

    def test_case_insensitive(self):
        from tr_shared.monitoring.adapters.noop import NoopMetricsAdapter
        result = MonitoringProviderFactory.create_metrics_provider("NOOP")
        assert isinstance(result, NoopMetricsAdapter)


# ---------------------------------------------------------------------------
# create_log_provider
# ---------------------------------------------------------------------------

class TestCreateLogProvider:
    def test_noop_returns_noop_log_adapter(self):
        from tr_shared.monitoring.adapters.noop import NoopLogAdapter
        result = MonitoringProviderFactory.create_log_provider("noop")
        assert isinstance(result, NoopLogAdapter)

    def test_loki_returns_loki_adapter(self):
        from tr_shared.monitoring.adapters.loki_log import LokiLogAdapter
        result = MonitoringProviderFactory.create_log_provider(
            "loki", loki_url="http://loki:3100/loki/api/v1/push"
        )
        assert isinstance(result, LokiLogAdapter)

    def test_invalid_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported log provider"):
            MonitoringProviderFactory.create_log_provider("unknown")

    def test_noop_case_insensitive(self):
        from tr_shared.monitoring.adapters.noop import NoopLogAdapter
        result = MonitoringProviderFactory.create_log_provider("NOOP")
        assert isinstance(result, NoopLogAdapter)


# ---------------------------------------------------------------------------
# create_trace_provider
# ---------------------------------------------------------------------------

class TestCreateTraceProvider:
    def test_noop_returns_noop_trace_adapter(self):
        from tr_shared.monitoring.adapters.noop import NoopTraceAdapter
        result = MonitoringProviderFactory.create_trace_provider("noop")
        assert isinstance(result, NoopTraceAdapter)

    def test_otlp_returns_otlp_adapter(self):
        from tr_shared.monitoring.adapters.otlp_trace import OtlpTraceAdapter
        result = MonitoringProviderFactory.create_trace_provider(
            "otlp", otlp_endpoint="http://tempo:4317"
        )
        assert isinstance(result, OtlpTraceAdapter)

    def test_invalid_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported trace provider"):
            MonitoringProviderFactory.create_trace_provider("splunk")
