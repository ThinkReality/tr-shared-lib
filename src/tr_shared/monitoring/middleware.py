"""
Metrics middleware — records HTTP request metrics via OpenTelemetry.

Extracted from tr-cms-service/app/core/telemetry.py (lines 176-258).
This is the ONLY existing implementation that correctly follows PRD v2.1
FR-1.2: tenant_id and user_id are EXCLUDED from Prometheus labels.

Labels (low-cardinality only):
    - ``service`` — service name (1 value per service)
    - ``http.route`` — normalized path (UUIDs → ``{id}``)
    - ``http.method`` — GET, POST, etc.
    - ``http.status_code`` — 200, 404, 500, etc.

Usage::

    from tr_shared.monitoring import MetricsMiddleware

    app.add_middleware(
        MetricsMiddleware,
        service_name="tr-listing-service",
        instrument_set=instruments,
    )
"""

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from tr_shared.monitoring.instruments import InstrumentSet
from tr_shared.monitoring.path_normalizer import normalize_path

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_PATHS: frozenset[str] = frozenset({
    "/",
    "/health",
    "/health/ready",
    "/health/live",
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/health/live",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
})


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Record HTTP request metrics with low-cardinality labels only.

    Args:
        app: ASGI application.
        service_name: Included in every metric as the ``service`` label.
        instrument_set: Pre-created OTel instruments from ``create_instruments()``.
        excluded_paths: Paths to skip (health, docs, metrics).
        business_domain_classifier: Optional callable ``(path) -> domain | None``.
            When provided and returns a non-None value, two extra metrics are
            recorded: ``{service}_business_requests`` and
            ``{service}_business_request_duration_seconds``.
    """

    def __init__(
        self,
        app,
        service_name: str = "unknown",
        instrument_set: InstrumentSet | None = None,
        excluded_paths: frozenset[str] | None = None,
        business_domain_classifier: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.instruments = instrument_set
        self.excluded_paths = excluded_paths or DEFAULT_EXCLUDED_PATHS
        self.business_domain_classifier = business_domain_classifier

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self.instruments is None:
            return await call_next(request)

        if request.url.path in self.excluded_paths:
            return await call_next(request)

        endpoint_pattern = normalize_path(request.url.path)
        method = request.method

        # Low-cardinality labels — NO tenant_id, NO user_id
        # Per PRD v2.1 FR-1.2: high-cardinality labels cause Prometheus
        # memory exhaustion. Use structured logs for per-tenant analysis.
        base_labels = {
            "service": self.service_name,
            "http.route": endpoint_pattern,
            "http.method": method,
        }

        # active_requests uses labels WITHOUT status_code (unknown until response)
        self.instruments.active_requests.add(1, base_labels)

        start = time.perf_counter()

        try:
            response = await call_next(request)
            status = response.status_code
            duration = time.perf_counter() - start

            labels = {**base_labels, "http.status_code": str(status)}

            self.instruments.request_counter.add(1, labels)
            self.instruments.request_duration.record(duration, labels)

            if status >= 400:
                self.instruments.error_counter.add(1, labels)

            # Optional business domain metrics
            if self.business_domain_classifier:
                domain = self.business_domain_classifier(request.url.path)
                if domain:
                    biz_labels = {
                        "service": self.service_name,
                        "domain": domain,
                        "http.method": method,
                        "http.status_code": str(status),
                    }
                    self.instruments.request_counter.add(1, biz_labels)
                    self.instruments.request_duration.record(duration, biz_labels)

            return response

        except Exception as exc:
            duration = time.perf_counter() - start
            labels = {**base_labels, "http.status_code": "500"}

            self.instruments.request_counter.add(1, labels)
            self.instruments.request_duration.record(duration, labels)
            self.instruments.error_counter.add(1, labels)

            logger.error(
                "Exception during request",
                extra={"error": str(exc), "endpoint": endpoint_pattern, "method": method},
            )
            raise

        finally:
            self.instruments.active_requests.add(-1, base_labels)
