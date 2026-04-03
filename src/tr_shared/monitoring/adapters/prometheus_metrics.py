"""Prometheus metrics adapter — delegates to existing prometheus_endpoint.py."""

from tr_shared.monitoring.interfaces import MetricsProviderInterface


class PrometheusMetricsAdapter(MetricsProviderInterface):
    """Wraps the existing Prometheus metric reader and endpoint server."""

    def create_metric_reader(self):
        from opentelemetry.exporter.prometheus import PrometheusMetricReader

        return PrometheusMetricReader()

    def start_server(self, port: int, service_name: str):
        if port <= 0:
            return None
        from tr_shared.monitoring.prometheus_endpoint import (
            start_prometheus_http_server,
        )

        return start_prometheus_http_server(port=port, service_name=service_name)

    def create_metrics_router(self):
        from tr_shared.monitoring.prometheus_endpoint import create_metrics_router

        return create_metrics_router()
