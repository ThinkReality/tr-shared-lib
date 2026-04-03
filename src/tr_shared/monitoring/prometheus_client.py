"""
Async Prometheus HTTP API client for the admin panel.

Wraps common PromQL queries with typed methods so the admin panel
can retrieve real-time metrics without building raw query strings.

Usage::

    from tr_shared.monitoring.prometheus_client import PrometheusClient

    client = PrometheusClient("http://tr-prometheus:9090")

    rate = await client.get_request_rate("crm-backend")
    overview = await client.get_service_overview("crm-backend")
    all_status = await client.get_all_services_status()

    await client.close()
"""

import logging

import httpx

logger = logging.getLogger(__name__)


class PrometheusClient:
    """
    Async client for querying the Prometheus HTTP API.

    Args:
        prometheus_url: Base URL (e.g. ``http://tr-prometheus:9090``).
        timeout: HTTP timeout in seconds.
    """

    def __init__(self, prometheus_url: str, timeout: float = 10.0) -> None:
        self._base_url = prometheus_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Instant queries ───────────────────────────────────────────────

    async def get_request_rate(
        self, service: str, window: str = "5m",
    ) -> float:
        """Total request rate (req/s) for a service."""
        promql = (
            f'sum(rate(http_server_requests_total{{service="{service}"}}[{window}]))'
        )
        return await self._query_scalar(promql, default=0.0)

    async def get_error_rate(
        self, service: str, window: str = "5m",
    ) -> float:
        """Error rate percentage for a service."""
        promql = (
            f'100 * sum(rate(http_server_errors_total{{service="{service}"}}[{window}]))'
            f' / sum(rate(http_server_requests_total{{service="{service}"}}[{window}]))'
        )
        return await self._query_scalar(promql, default=0.0)

    async def get_p95_latency(
        self, service: str, window: str = "5m",
    ) -> float:
        """P95 response time in seconds."""
        promql = (
            f'histogram_quantile(0.95, '
            f'sum(rate(http_server_request_duration_seconds_bucket{{service="{service}"}}[{window}])) by (le))'
        )
        return await self._query_scalar(promql, default=0.0)

    async def get_p99_latency(
        self, service: str, window: str = "5m",
    ) -> float:
        """P99 response time in seconds."""
        promql = (
            f'histogram_quantile(0.99, '
            f'sum(rate(http_server_request_duration_seconds_bucket{{service="{service}"}}[{window}])) by (le))'
        )
        return await self._query_scalar(promql, default=0.0)

    async def get_active_requests(self, service: str) -> int:
        """Currently active requests for a service."""
        promql = f'sum(http_server_active_requests{{service="{service}"}})'
        return int(await self._query_scalar(promql, default=0.0))

    async def is_service_up(self, service: str) -> bool:
        """Check if Prometheus can scrape the service."""
        promql = f'up{{job="{service}"}}'
        value = await self._query_scalar(promql, default=0.0)
        return value == 1.0

    async def get_service_overview(self, service: str) -> dict:
        """
        All-in-one overview for a service.

        Returns:
            Dict with keys: request_rate, error_rate, p95_latency_s,
            p99_latency_s, active_requests, is_up.
        """
        # Execute queries in parallel would be ideal, but sequential
        # is simpler and Prometheus queries are fast (~1ms each)
        return {
            "service": service,
            "request_rate": await self.get_request_rate(service),
            "error_rate": await self.get_error_rate(service),
            "p95_latency_s": await self.get_p95_latency(service),
            "p99_latency_s": await self.get_p99_latency(service),
            "active_requests": await self.get_active_requests(service),
            "is_up": await self.is_service_up(service),
        }

    async def get_all_services_status(self) -> list[dict]:
        """
        Health status of all scraped services.

        Returns:
            List of dicts with service name and up/down status.
        """
        result = await self._query("up")
        services = []
        for item in result:
            metric = item.get("metric", {})
            value = item.get("value", [None, "0"])
            services.append({
                "service": metric.get("job", "unknown"),
                "is_up": float(value[1]) == 1.0 if len(value) > 1 else False,
            })
        return services

    async def get_top_endpoints(
        self, service: str, limit: int = 10, window: str = "5m",
    ) -> list[dict]:
        """
        Top endpoints by request rate.

        Returns:
            List of dicts with endpoint, method, and request_rate.
        """
        promql = (
            f'topk({limit}, sum by (http_route, http_method) '
            f'(rate(http_server_requests_total{{service="{service}"}}[{window}])))'
        )
        result = await self._query(promql)
        endpoints = []
        for item in result:
            metric = item.get("metric", {})
            value = item.get("value", [None, "0"])
            endpoints.append({
                "endpoint": metric.get("http_route", metric.get("http.route", "unknown")),
                "method": metric.get("http_method", metric.get("http.method", "")),
                "request_rate": float(value[1]) if len(value) > 1 else 0.0,
            })
        return endpoints

    # ── Internal helpers ──────────────────────────────────────────────

    async def _query(self, promql: str) -> list[dict]:
        """Execute a PromQL instant query, return the result vector."""
        try:
            resp = await self._client.get(
                "/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "success":
                logger.warning("Prometheus query failed: %s", data.get("error"))
                return []

            return data.get("data", {}).get("result", [])

        except httpx.HTTPError as exc:
            logger.error("Prometheus query error: %s", exc)
            return []

    async def _query_scalar(self, promql: str, default: float = 0.0) -> float:
        """Execute a PromQL query and return the first scalar value."""
        result = await self._query(promql)
        if not result:
            return default

        try:
            value = result[0].get("value", [None, str(default)])
            parsed = float(value[1]) if len(value) > 1 else default
            # Handle NaN/Inf from Prometheus (e.g. division by zero)
            if parsed != parsed or parsed == float("inf"):
                return default
            return parsed
        except (IndexError, ValueError, TypeError):
            return default
