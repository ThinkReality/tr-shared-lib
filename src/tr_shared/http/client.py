"""
Shared async HTTP client for service-to-service communication.

Extracted from TR-HR-System-be's ServiceHTTPClient — the cleanest
implementation with circuit breaker, retry, exponential backoff, and
correlation ID propagation.

Usage::

    from tr_shared.http import ServiceHTTPClient

    client = ServiceHTTPClient(
        service_name="crm-backend",
        base_url="http://crm-backend:8000",
        service_token="secret",
    )
    result = await client.get("/internal/auth-context/abc-123")
    await client.close()
"""

import asyncio
import json as json_lib
import logging
from typing import Any

import httpx

from tr_shared.http.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class ServiceHTTPClient:
    """
    HTTP client for internal service-to-service communication.

    Features:
        - Circuit breaker pattern (fail-fast when target is down)
        - Exponential backoff retry
        - Service token authentication
        - Correlation ID propagation
        - Context manager support
    """

    def __init__(
        self,
        service_name: str,
        base_url: str,
        service_token: str = "",
        timeout: float = 30.0,
        max_retries: int = 3,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ) -> None:
        self.service_name = service_name
        self.base_url = base_url
        self.service_token = service_token
        self.timeout = timeout
        self.max_retries = max_retries
        self.circuit = CircuitBreaker(
            name=service_name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self.service_token:
                headers["X-Service-Token"] = self.service_token
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Convenience verbs ────────────────────────────────────────────

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", path, json=json, headers=headers)

    async def put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._request("PUT", path, json=json, headers=headers)

    async def patch(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._request("PATCH", path, json=json, headers=headers)

    async def delete(
        self,
        path: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._request("DELETE", path, headers=headers)

    # ── Core request logic ───────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if await self.circuit.is_open():
            raise ConnectionError(
                f"Circuit breaker open for {self.service_name} — requests rejected"
            )

        client = await self._get_client()
        last_exc: Exception | None = None

        # Auto-inject correlation ID from structlog contextvars if available
        merged_headers = dict(headers) if headers else {}
        if "X-Correlation-ID" not in merged_headers:
            try:
                from structlog.contextvars import get_contextvars

                ctx = get_contextvars()
                cid = ctx.get("correlation_id")
                if cid:
                    merged_headers["X-Correlation-ID"] = str(cid)
            except Exception:
                pass

        for attempt in range(self.max_retries):
            try:
                response = await client.request(
                    method=method,
                    url=path,
                    params=params,
                    json=json,
                    headers=merged_headers,
                )
                response.raise_for_status()
                await self.circuit.record_success()

                if response.status_code == 204:
                    return {}

                content_type = response.headers.get("content-type", "").lower()
                if "application/json" not in content_type:
                    return {"raw": response.text}

                try:
                    return response.json()
                except (json_lib.JSONDecodeError, ValueError):
                    return {"raw": response.text}

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                # Client errors (4xx) — don't trip the breaker, don't retry
                if 400 <= exc.response.status_code < 500:
                    raise
                await self.circuit.record_failure()

            except httpx.RequestError as exc:
                last_exc = exc
                await self.circuit.record_failure()
                logger.error(
                    "Request error calling %s: %s", self.service_name, exc
                )

            # Exponential backoff before next retry
            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        raise ConnectionError(
            f"{self.service_name}: failed after {self.max_retries} retries"
        ) from last_exc

    # ── Context manager ──────────────────────────────────────────────

    async def __aenter__(self) -> "ServiceHTTPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
