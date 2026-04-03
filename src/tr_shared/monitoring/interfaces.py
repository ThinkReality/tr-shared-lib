"""
Abstract base classes for the monitoring provider abstraction layer.

Defines contracts that all monitoring adapters must implement,
ensuring the rest of the application is decoupled from any
specific observability provider (Prometheus, Loki, OTLP, etc.).

Follows the same ABC pattern as ``cache/interface.py``.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any


class MetricsProviderInterface(ABC):
    """Contract for metrics export providers (e.g. Prometheus, Datadog)."""

    @abstractmethod
    def create_metric_reader(self) -> Any | None:
        """Return an OpenTelemetry MetricReader, or None to disable metrics export."""
        ...

    @abstractmethod
    def start_server(self, port: int, service_name: str) -> Any | None:
        """Start a metrics scrape server (e.g. Prometheus HTTP server).

        Returns:
            Server handle for shutdown, or None if not applicable.
        """
        ...

    @abstractmethod
    def create_metrics_router(self) -> Any | None:
        """Return a FastAPI APIRouter exposing a ``/metrics`` endpoint, or None."""
        ...


class LogProviderInterface(ABC):
    """Contract for log shipping providers (e.g. Loki, BetterStack)."""

    @abstractmethod
    def create_handler(
        self, service_name: str, labels: dict[str, str]
    ) -> logging.Handler:
        """Return a ``logging.Handler`` that ships logs to the backend.

        Args:
            service_name: Identifies the originating service.
            labels: Static low-cardinality labels (e.g. environment, service).

        Returns:
            A configured logging handler.
        """
        ...


class TraceProviderInterface(ABC):
    """Contract for trace export providers (e.g. OTLP/gRPC, Jaeger)."""

    @abstractmethod
    def create_span_exporter(self) -> Any | None:
        """Return an OpenTelemetry SpanExporter, or None to disable trace export."""
        ...
