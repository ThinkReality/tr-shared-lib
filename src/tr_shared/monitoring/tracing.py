"""
Optional distributed tracing via OpenTelemetry → Grafana Tempo.

Extracted from tr-cms-service/app/core/telemetry.py (lines 78-112).

When ``otlp_endpoint`` is provided, spans are exported via OTLP/gRPC
(e.g. to Grafana Tempo at ``http://tempo:4317``). When empty, the
TracerProvider is initialised with no exporters — instrumentation still
works locally for debugging but nothing is shipped.

Usage::

    from tr_shared.monitoring.tracing import setup_tracing

    # In lifespan startup
    provider = setup_tracing("tr-cms-service", otlp_endpoint="http://tempo:4317")

    # In lifespan shutdown
    provider.shutdown()
"""

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)


def setup_tracing(
    service_name: str,
    otlp_endpoint: str = "",
    span_exporter: object | None = None,
) -> TracerProvider:
    """
    Initialise OpenTelemetry tracing.

    Args:
        service_name: Attached to every span as ``service.name``.
        otlp_endpoint: OTLP gRPC collector endpoint (e.g. ``http://tempo:4317``).
            Empty string disables remote export.
        span_exporter: Pre-built SpanExporter injected by the monitoring
            factory.  When provided, *otlp_endpoint* is ignored.

    Returns:
        TracerProvider — call ``.shutdown()`` on application teardown.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # Prefer an explicitly injected exporter (from the factory abstraction)
    exporter = span_exporter
    if exporter is None and otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)

    if exporter is not None:
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "Tracing initialised with exporter",
            extra={
                "service": service_name,
                "exporter_type": type(exporter).__name__,
                "otlp_endpoint": otlp_endpoint or "(injected)",
            },
        )
    else:
        logger.info(
            "Tracing initialised (no exporter — set OTEL_EXPORTER_OTLP_ENDPOINT to enable)",
            extra={"service": service_name},
        )

    trace.set_tracer_provider(provider)
    return provider
