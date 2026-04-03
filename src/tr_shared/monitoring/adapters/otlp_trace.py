"""OTLP trace adapter — wraps the conditional OTLP import from tracing.py."""

from tr_shared.monitoring.interfaces import TraceProviderInterface


class OtlpTraceAdapter(TraceProviderInterface):
    """Wraps OpenTelemetry OTLP/gRPC span exporter."""

    def __init__(self, endpoint: str = "") -> None:
        self.endpoint = endpoint

    def create_span_exporter(self):
        if not self.endpoint:
            return None
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter(endpoint=self.endpoint)
