"""No-op monitoring adapters for disabling any observability pillar."""

import logging

from tr_shared.monitoring.interfaces import (
    LogProviderInterface,
    MetricsProviderInterface,
    TraceProviderInterface,
)


class NoopMetricsAdapter(MetricsProviderInterface):
    """Metrics adapter that does nothing — disables metrics export."""

    def create_metric_reader(self):
        return None

    def start_server(self, port: int, service_name: str):
        return None

    def create_metrics_router(self):
        return None


class NoopLogAdapter(LogProviderInterface):
    """Log adapter that does nothing — disables log shipping."""

    def create_handler(
        self, service_name: str, labels: dict[str, str]
    ) -> logging.Handler:
        return logging.NullHandler()


class NoopTraceAdapter(TraceProviderInterface):
    """Trace adapter that does nothing — disables trace export."""

    def create_span_exporter(self):
        return None
