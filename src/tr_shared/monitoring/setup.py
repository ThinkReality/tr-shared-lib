"""
One-call monitoring setup for any ThinkRealty service.

Wires up OpenTelemetry metrics middleware, optional Prometheus exporter,
optional distributed tracing, and optional log shipping in a single
function call.

Provider selection is config-driven via the ``metrics_provider``,
``log_provider``, and ``trace_provider`` parameters.  Defaults match
the current Grafana Stack (Prometheus + Loki + OTLP), so **zero service
changes are required** when upgrading to this version.

Usage::

    from tr_shared.monitoring import setup_monitoring

    # Current behavior — unchanged
    setup_monitoring(
        app=app,
        service_name=settings.SERVICE_NAME,
        prometheus_port=settings.PROMETHEUS_PORT,
    )

    # Disable metrics export (e.g. for tests)
    setup_monitoring(
        app=app,
        service_name="test",
        metrics_provider="noop",
    )

    # With optional business domain classification
    def classify(path: str) -> str | None:
        if path.startswith("/api/v1/blogs"):
            return "blogs"
        return None

    setup_monitoring(
        app=app,
        service_name="tr-cms-service",
        business_domain_classifier=classify,
    )
"""

import logging
from collections.abc import Callable

from fastapi import FastAPI
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource

from tr_shared.monitoring.factory import MonitoringProviderFactory
from tr_shared.monitoring.instruments import create_instruments
from tr_shared.monitoring.middleware import MetricsMiddleware
from tr_shared.monitoring.tracing import setup_tracing

logger = logging.getLogger(__name__)


def setup_monitoring(
    app: FastAPI,
    service_name: str,
    prometheus_port: int = 9090,
    enable_tracing: bool = False,
    otlp_endpoint: str = "",
    excluded_paths: frozenset[str] | None = None,
    business_domain_classifier: Callable[[str], str | None] | None = None,
    # ── Layer 2: persistence to central monitoring DB ──
    enable_persistence: bool = False,
    redis_url: str = "",
    # ── Log shipping ──
    loki_url: str = "",
    environment: str = "",
    # ── Provider selection (defaults = current Grafana Stack behavior) ──
    metrics_provider: str = "prometheus",
    log_provider: str = "loki",
    trace_provider: str = "otlp",
) -> None:
    """
    Configure monitoring for a FastAPI service.

    Must be called **before** the app starts serving requests
    (typically in the lifespan startup handler).

    Args:
        app: FastAPI application instance.
        service_name: Identifies this service in metrics and traces.
        prometheus_port: Port for the standalone metrics HTTP server.
            Set to 0 to skip starting the server (use ``create_metrics_router``
            instead for same-port serving).
        enable_tracing: Enable distributed tracing export.
        otlp_endpoint: OTLP gRPC endpoint (e.g. ``http://tempo:4317``).
            Only used when *enable_tracing* is True.
        excluded_paths: Paths to skip (defaults to health/docs/metrics).
        business_domain_classifier: Optional ``(path) -> domain | None`` hook
            for recording business-domain-specific metrics.
        enable_persistence: Enable Layer 2 request persistence to Redis
            buffer (flushed to central monitoring DB by Celery tasks).
        redis_url: Redis URL for the persistence buffer.
            Required when *enable_persistence* is True.
        loki_url: Log shipping URL. For Loki this is the push API URL
            (e.g. ``http://loki:3100/loki/api/v1/push``).
            When set, a log handler is attached to the root logger.
        environment: Environment name (dev, staging, prod) used as a log label.
        metrics_provider: Metrics backend — ``"prometheus"`` (default) or ``"noop"``.
        log_provider: Log shipping backend — ``"loki"`` (default) or ``"noop"``.
        trace_provider: Trace export backend — ``"otlp"`` (default) or ``"noop"``.
    """
    # 1. Metrics: create reader via factory + MeterProvider
    metrics_adapter = MonitoringProviderFactory.create_metrics_provider(
        provider=metrics_provider
    )
    reader = metrics_adapter.create_metric_reader()
    readers = [reader] if reader else []

    resource = Resource.create({"service.name": service_name})
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=readers,
    )
    metrics.set_meter_provider(meter_provider)

    # 2. Create standard HTTP instruments
    meter = metrics.get_meter("tr_shared.monitoring")
    instrument_set = create_instruments(meter)

    # 3. Add metrics middleware
    app.add_middleware(
        MetricsMiddleware,
        service_name=service_name,
        instrument_set=instrument_set,
        excluded_paths=excluded_paths,
        business_domain_classifier=business_domain_classifier,
    )

    # 4. Start metrics HTTP server (unless port=0)
    if prometheus_port > 0:
        metrics_adapter.start_server(port=prometheus_port, service_name=service_name)

    # 5. Optional distributed tracing via factory
    if enable_tracing:
        trace_adapter = MonitoringProviderFactory.create_trace_provider(
            provider=trace_provider,
            otlp_endpoint=otlp_endpoint,
        )
        span_exporter = trace_adapter.create_span_exporter()
        setup_tracing(
            service_name=service_name,
            otlp_endpoint=otlp_endpoint,
            span_exporter=span_exporter,
        )

    # 6. Optional Layer 2 persistence (Redis buffer -> central DB)
    if enable_persistence and redis_url:
        from tr_shared.monitoring.persistence import PersistenceMiddleware

        app.add_middleware(
            PersistenceMiddleware,
            service_name=service_name,
            redis_url=redis_url,
            excluded_paths=excluded_paths,
        )

    # 7. Optional log shipping via factory
    if loki_url:
        log_adapter = MonitoringProviderFactory.create_log_provider(
            provider=log_provider,
            loki_url=loki_url,
        )

        loki_labels: dict[str, str] = {}
        if environment:
            loki_labels["environment"] = environment

        log_handler = log_adapter.create_handler(
            service_name=service_name,
            labels=loki_labels,
        )
        log_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(log_handler)

    logger.info(
        "Monitoring configured",
        extra={
            "service": service_name,
            "prometheus_port": prometheus_port,
            "tracing": enable_tracing,
            "persistence": enable_persistence and bool(redis_url),
            "log_shipping": bool(loki_url),
            "metrics_provider": metrics_provider,
            "log_provider": log_provider,
            "trace_provider": trace_provider,
        },
    )
