"""Tests for setup_monitoring — uses mocks to avoid real OTel setup."""

import pytest
from fastapi import FastAPI
from unittest.mock import MagicMock, patch, call


class TestSetupMonitoring:
    def _make_app(self):
        return FastAPI()

    def test_adds_metrics_middleware_to_app(self):
        """setup_monitoring must add MetricsMiddleware to the app."""
        from tr_shared.monitoring.setup import setup_monitoring

        app = self._make_app()
        with patch("tr_shared.monitoring.setup.MonitoringProviderFactory") as mock_factory, \
             patch("tr_shared.monitoring.setup.MeterProvider"), \
             patch("tr_shared.monitoring.setup.metrics"), \
             patch("tr_shared.monitoring.setup.create_instruments") as mock_instruments:

            mock_adapter = MagicMock()
            mock_adapter.create_metric_reader.return_value = MagicMock()
            mock_adapter.start_server = MagicMock()
            mock_factory.create_metrics_provider.return_value = mock_adapter
            mock_instruments.return_value = MagicMock()

            with patch("tr_shared.monitoring.middleware.MetricsMiddleware"):
                setup_monitoring(app, "test-svc", prometheus_port=0)

            # MetricsMiddleware was added to the app's middleware stack
            from tr_shared.monitoring.middleware import MetricsMiddleware
            middleware_types = [m.cls for m in app.user_middleware]
            assert MetricsMiddleware in middleware_types

    def test_calls_create_metrics_provider_with_correct_provider(self):
        app = self._make_app()
        from tr_shared.monitoring.setup import setup_monitoring

        with patch("tr_shared.monitoring.setup.MonitoringProviderFactory") as mock_factory, \
             patch("tr_shared.monitoring.setup.MeterProvider"), \
             patch("tr_shared.monitoring.setup.metrics"), \
             patch("tr_shared.monitoring.setup.create_instruments", return_value=MagicMock()):

            mock_adapter = MagicMock()
            mock_adapter.create_metric_reader.return_value = None
            mock_adapter.start_server = MagicMock()
            mock_factory.create_metrics_provider.return_value = mock_adapter

            setup_monitoring(app, "test-svc", prometheus_port=0, metrics_provider="noop")
            mock_factory.create_metrics_provider.assert_called_once_with(provider="noop")

    def test_does_not_call_tracing_when_disabled(self):
        app = self._make_app()
        from tr_shared.monitoring.setup import setup_monitoring

        with patch("tr_shared.monitoring.setup.MonitoringProviderFactory") as mock_factory, \
             patch("tr_shared.monitoring.setup.MeterProvider"), \
             patch("tr_shared.monitoring.setup.metrics"), \
             patch("tr_shared.monitoring.setup.create_instruments", return_value=MagicMock()), \
             patch("tr_shared.monitoring.setup.setup_tracing") as mock_tracing:

            mock_adapter = MagicMock()
            mock_adapter.create_metric_reader.return_value = None
            mock_adapter.start_server = MagicMock()
            mock_factory.create_metrics_provider.return_value = mock_adapter

            setup_monitoring(app, "test-svc", prometheus_port=0, enable_tracing=False)
            mock_tracing.assert_not_called()

    def test_calls_tracing_when_enabled(self):
        app = self._make_app()
        from tr_shared.monitoring.setup import setup_monitoring

        with patch("tr_shared.monitoring.setup.MonitoringProviderFactory") as mock_factory, \
             patch("tr_shared.monitoring.setup.MeterProvider"), \
             patch("tr_shared.monitoring.setup.metrics"), \
             patch("tr_shared.monitoring.setup.create_instruments", return_value=MagicMock()), \
             patch("tr_shared.monitoring.setup.setup_tracing") as mock_tracing:

            mock_adapter = MagicMock()
            mock_adapter.create_metric_reader.return_value = None
            mock_adapter.start_server = MagicMock()
            mock_trace_adapter = MagicMock()
            mock_factory.create_metrics_provider.return_value = mock_adapter
            mock_factory.create_trace_provider.return_value = mock_trace_adapter

            setup_monitoring(
                app, "test-svc", prometheus_port=0,
                enable_tracing=True, otlp_endpoint="http://tempo:4317"
            )
            mock_tracing.assert_called_once()

    def test_does_not_call_log_provider_without_loki_url(self):
        app = self._make_app()
        from tr_shared.monitoring.setup import setup_monitoring

        with patch("tr_shared.monitoring.setup.MonitoringProviderFactory") as mock_factory, \
             patch("tr_shared.monitoring.setup.MeterProvider"), \
             patch("tr_shared.monitoring.setup.metrics"), \
             patch("tr_shared.monitoring.setup.create_instruments", return_value=MagicMock()):

            mock_adapter = MagicMock()
            mock_adapter.create_metric_reader.return_value = None
            mock_adapter.start_server = MagicMock()
            mock_factory.create_metrics_provider.return_value = mock_adapter

            setup_monitoring(app, "test-svc", prometheus_port=0, loki_url="")
            mock_factory.create_log_provider.assert_not_called()

    def test_calls_log_provider_when_loki_url_set(self):
        app = self._make_app()
        from tr_shared.monitoring.setup import setup_monitoring

        with patch("tr_shared.monitoring.setup.MonitoringProviderFactory") as mock_factory, \
             patch("tr_shared.monitoring.setup.MeterProvider"), \
             patch("tr_shared.monitoring.setup.metrics"), \
             patch("tr_shared.monitoring.setup.create_instruments", return_value=MagicMock()), \
             patch("logging.getLogger"):

            mock_adapter = MagicMock()
            mock_adapter.create_metric_reader.return_value = None
            mock_adapter.start_server = MagicMock()
            mock_log_adapter = MagicMock()
            mock_log_handler = MagicMock()
            mock_log_adapter.create_handler.return_value = mock_log_handler
            mock_factory.create_metrics_provider.return_value = mock_adapter
            mock_factory.create_log_provider.return_value = mock_log_adapter

            setup_monitoring(
                app, "test-svc", prometheus_port=0,
                loki_url="http://loki:3100/loki/api/v1/push"
            )
            mock_factory.create_log_provider.assert_called_once()
