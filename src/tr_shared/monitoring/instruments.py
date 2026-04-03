"""
Standard OpenTelemetry instruments for HTTP metrics.

Extracted from tr-cms-service/app/core/telemetry.py (lines 140-172).
Single source of truth for metric names — no service creates its own.

The four standard instruments follow OpenTelemetry semantic conventions:
- ``http_server_requests`` (Counter)
- ``http_server_request_duration_seconds`` (Histogram)
- ``http_server_errors`` (Counter)
- ``http_server_active_requests`` (UpDownCounter)
"""

from dataclasses import dataclass

from opentelemetry.metrics import Counter, Histogram, Meter, UpDownCounter


@dataclass(frozen=True)
class InstrumentSet:
    """Typed container for the four standard HTTP instruments."""

    request_counter: Counter
    request_duration: Histogram
    error_counter: Counter
    active_requests: UpDownCounter


def create_instruments(meter: Meter) -> InstrumentSet:
    """
    Create the standard set of HTTP instruments.

    Args:
        meter: OpenTelemetry Meter instance.

    Returns:
        InstrumentSet with all four instruments ready to record.
    """
    return InstrumentSet(
        request_counter=meter.create_counter(
            name="http_server_requests",
            description="Total HTTP requests",
            unit="{request}",
        ),
        request_duration=meter.create_histogram(
            name="http_server_request_duration_seconds",
            description="HTTP request duration in seconds",
            unit="s",
        ),
        error_counter=meter.create_counter(
            name="http_server_errors",
            description="Total HTTP errors (status >= 400)",
            unit="{error}",
        ),
        active_requests=meter.create_up_down_counter(
            name="http_server_active_requests",
            description="Currently active HTTP requests",
            unit="{request}",
        ),
    )
