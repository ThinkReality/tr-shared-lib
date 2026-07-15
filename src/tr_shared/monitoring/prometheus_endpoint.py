"""
Prometheus metrics endpoint — two serving strategies.

Strategy 1 — Separate HTTP server (standard):
    Prometheus scrapes a dedicated port (e.g. 9090). Used by CMS + CRM.
    Best when your infrastructure can expose multiple ports.

Strategy 2 — FastAPI route:
    Mount ``GET /metrics`` on the main app. Useful on Railway where
    extra ports cost extra or are harder to expose.
"""

import errno
import logging

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    generate_latest,
    start_http_server,
)

logger = logging.getLogger(__name__)


def start_prometheus_http_server(
    port: int = 9090,
    bind_address: str = "0.0.0.0",
    service_name: str = "unknown",
):
    """
    Start a standalone Prometheus HTTP server on *port*.

    Args:
        port: TCP port for ``/metrics``.
        bind_address: Interface to bind.
        service_name: For log messages only.

    Returns:
        The HTTPServer instance (call ``.shutdown()`` on teardown).
    """
    try:
        server = start_http_server(port=port, addr=bind_address)
        logger.info(
            "Prometheus metrics server started",
            extra={
                "service": service_name,
                "prometheus_port": port,
                "metrics_url": f"http://{bind_address}:{port}/metrics",
            },
        )
        return server
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            logger.warning(
                "Prometheus port %d already in use — skipping (hot-reload?)",
                port,
                extra={"service": service_name, "port": port},
            )
            return None
        logger.error(
            "Failed to start Prometheus metrics server",
            extra={"error": str(exc), "port": port},
        )
        raise


def create_metrics_router():
    """Return a FastAPI ``APIRouter`` with a ``GET /metrics`` endpoint."""
    from fastapi import APIRouter
    from fastapi.responses import Response

    router = APIRouter(tags=["monitoring"])

    @router.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return router
