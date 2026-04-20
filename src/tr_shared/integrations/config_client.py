"""Client for fetching integration configuration from the admin panel.

Pattern mirrors shared-auth-lib's AuthContextClient (see
shared-auth-lib/shared_auth_lib/services/auth_context_client.py). Key
deviations dictated by the spec (docs/specs/01-batch-foundation.md §1A):

  1. Per-key asyncio.Lock for stampede protection (admin panel does a
     Vault decrypt per call, so stampede cost is high — AuthContextClient
     doesn't need this).
  2. `warm_all(platform_name)` batch-fetches all enabled tenants with a
     concurrency cap of 10 via Semaphore.
  3. `include_secrets: bool` toggle on the admin-panel endpoint; default
     False; audit-log emitted when True.
  4. Cache key includes `include_secrets` so a no-secret entry cannot
     accidentally satisfy a secret-requesting call.

The client caches results in-memory only. Event invalidation (via
register_integration_cache_handlers) + the 1800s local TTL are the
freshness mechanisms. There is no Redis tier on the client itself —
the admin-panel is the single source of truth.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Any

import httpx

from tr_shared.http.circuit_breaker import CircuitBreaker
from tr_shared.integrations.exceptions import (
    IntegrationConfigError,
    IntegrationConfigNotFound,
)
from tr_shared.integrations.models import IntegrationConfig

logger = logging.getLogger("tr_shared.integrations")


class IntegrationConfigClient:
    """Admin-panel-backed integration configuration client.

    Construct one instance per process; call init_integration_config_client()
    to register it in the DI registry. Services never instantiate this
    twice in a single process.
    """

    def __init__(
        self,
        admin_panel_url: str,
        service_token: str,
        *,
        timeout: float = 5.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: int = 30,
        redis_client: Any = None,
        local_cache_ttl: int = 1800,
        local_cache_max_size: int = 500,
        warm_all_concurrency: int = 10,
    ) -> None:
        self._admin_panel_url = admin_panel_url.rstrip("/")
        self._service_token = service_token
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._admin_panel_url,
            timeout=httpx.Timeout(timeout),
        )
        self._circuit = CircuitBreaker(
            name="integration-config-client",
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_timeout,
            redis_client=redis_client,
        )
        # FIFO cache: {cache_key: (expires_at_monotonic, IntegrationConfig)}
        self._local_cache: dict[str, tuple[float, IntegrationConfig]] = {}
        self._local_cache_ttl = local_cache_ttl
        self._local_cache_max_size = local_cache_max_size
        # Per-key stampede locks
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._warm_semaphore = asyncio.Semaphore(warm_all_concurrency)
        self._service_name = os.getenv("SERVICE_NAME", "unknown")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_config(
        self,
        tenant_id: str,
        platform_name: str,
        *,
        include_secrets: bool = False,
        correlation_id: str | None = None,
    ) -> IntegrationConfig:
        """Fetch per-tenant integration configuration.

        When `include_secrets=False` (the default), the returned config
        contains only non-sensitive JSONB fields. When True, Vault-decrypted
        secrets are merged in and an audit log is emitted.

        Raises:
            IntegrationConfigNotFound: 404 from admin panel.
            IntegrationConfigError: circuit open, HTTP 5xx, network error.
        """
        cache_key = self._cache_key(tenant_id, platform_name, include_secrets)

        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # Per-key lock prevents stampede — only one coroutine fetches
        # per (tenant, platform, include_secrets) at a time.
        async with self._locks[cache_key]:
            # Double-check — another coroutine may have populated while we waited.
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                return cached

            config = await self._fetch_config(
                tenant_id, platform_name, include_secrets, correlation_id
            )

            if include_secrets:
                self._emit_secrets_audit_log(tenant_id, platform_name, correlation_id)

            self._put_in_cache(cache_key, config)

        # Release the lock entry once populated — bounds memory. A new
        # concurrent miss on the same key after eviction will allocate
        # a fresh lock via defaultdict.
        self._locks.pop(cache_key, None)
        return config

    async def get_enabled_tenants(self, platform_name: str) -> list[str]:
        """Return list of tenant UUIDs with an active+enabled row for this platform."""
        if await self._circuit.is_open():
            raise IntegrationConfigError("Circuit open: admin panel unavailable")

        try:
            response = await self._client.get(
                f"/api/v1/internal/integrations/platforms/{platform_name}/tenants",
                headers={"X-Service-Token": self._service_token},
            )
        except httpx.HTTPError as exc:
            await self._circuit.record_failure()
            raise IntegrationConfigError(
                f"get_enabled_tenants network error: {exc.__class__.__name__}"
            ) from exc

        if response.status_code != 200:
            await self._circuit.record_failure()
            raise IntegrationConfigError(
                f"get_enabled_tenants returned HTTP {response.status_code}"
            )

        await self._circuit.record_success()
        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        tenants = data.get("tenant_ids", []) if isinstance(data, dict) else []
        return [str(t) for t in tenants]

    async def warm_all(self, platform_name: str) -> int:
        """Pre-warm the cache for every enabled tenant of this platform.

        Calls the bulk-tenant-list endpoint, then fetches each tenant's
        config with include_secrets=True at concurrency cap
        `warm_all_concurrency`. Returns the number of successful warms.
        Partial failures are logged but do NOT raise.
        """
        tenant_ids = await self.get_enabled_tenants(platform_name)
        if not tenant_ids:
            return 0

        async def _warm_one(tid: str) -> bool:
            async with self._warm_semaphore:
                try:
                    await self.get_config(tid, platform_name, include_secrets=True)
                    return True
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "integration_warm_tenant_failed",
                        extra={
                            "tenant_id": tid,
                            "platform_name": platform_name,
                            "error": str(exc),
                        },
                    )
                    return False

        results = await asyncio.gather(*(_warm_one(t) for t in tenant_ids))
        return sum(1 for r in results if r)

    def invalidate_cache(
        self,
        tenant_id: str | None = None,
        platform_name: str | None = None,
    ) -> None:
        """Invalidate cached entries.

        - ``(None, None)``        → clear entire cache.
        - ``(tenant_id, None)``   → clear every entry for that tenant.
        - ``(None, platform)``    → clear every entry for that platform.
        - both set                → clear only the matching pair.
        """
        if tenant_id is None and platform_name is None:
            self._local_cache.clear()
            return

        # Cache keys are "tenant_id:platform_name:include_secrets"
        keys_to_remove = [
            key
            for key in self._local_cache
            if self._key_matches(key, tenant_id, platform_name)
        ]
        for key in keys_to_remove:
            del self._local_cache[key]

    async def close(self) -> None:
        """Close the HTTP client and drain the cache."""
        self._local_cache.clear()
        await self._client.aclose()

    async def __aenter__(self) -> IntegrationConfigClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_config(
        self,
        tenant_id: str,
        platform_name: str,
        include_secrets: bool,
        correlation_id: str | None,
    ) -> IntegrationConfig:
        if await self._circuit.is_open():
            raise IntegrationConfigError("Circuit open: admin panel unavailable")

        url = (
            f"/api/v1/internal/integrations/platforms/{platform_name}"
            f"/tenants/{tenant_id}"
        )
        headers = {"X-Service-Token": self._service_token}
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        params = {"include_secrets": "true" if include_secrets else "false"}

        try:
            response = await self._client.get(url, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            await self._circuit.record_failure()
            raise IntegrationConfigError(
                f"admin panel timeout for tenant={tenant_id} platform={platform_name}"
            ) from exc
        except httpx.HTTPError as exc:
            await self._circuit.record_failure()
            raise IntegrationConfigError(
                f"admin panel network error: {exc.__class__.__name__}"
            ) from exc

        if response.status_code == 404:
            # 404 is a logical not-found, NOT a circuit-worthy failure.
            raise IntegrationConfigNotFound(
                f"No active integration for tenant={tenant_id} platform={platform_name}"
            )
        if response.status_code != 200:
            await self._circuit.record_failure()
            raise IntegrationConfigError(
                f"admin panel returned HTTP {response.status_code} "
                f"for tenant={tenant_id} platform={platform_name}"
            )

        await self._circuit.record_success()
        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(data, dict):
            raise IntegrationConfigError(
                "admin panel returned malformed response (not a dict)"
            )

        try:
            return IntegrationConfig(**data)
        except Exception as exc:
            raise IntegrationConfigError(
                f"admin panel response failed IntegrationConfig validation: {exc}"
            ) from exc

    def _cache_key(
        self, tenant_id: str, platform_name: str, include_secrets: bool
    ) -> str:
        return f"{tenant_id}:{platform_name}:{int(include_secrets)}"

    def _key_matches(
        self,
        key: str,
        tenant_id: str | None,
        platform_name: str | None,
    ) -> bool:
        # key format: "tenant:platform:secret_flag"
        parts = key.rsplit(":", 2)
        if len(parts) != 3:
            return False
        key_tenant, key_platform, _ = parts
        if tenant_id is not None and key_tenant != tenant_id:
            return False
        if platform_name is not None and key_platform != platform_name:
            return False
        return True

    def _get_from_cache(self, key: str) -> IntegrationConfig | None:
        entry = self._local_cache.get(key)
        if entry is None:
            return None
        expires_at, config = entry
        if time.monotonic() > expires_at:
            del self._local_cache[key]
            return None
        return config

    def _put_in_cache(self, key: str, config: IntegrationConfig) -> None:
        if len(self._local_cache) >= self._local_cache_max_size:
            # FIFO eviction — drop the oldest entry.
            oldest = next(iter(self._local_cache))
            del self._local_cache[oldest]
        self._local_cache[key] = (
            time.monotonic() + self._local_cache_ttl,
            config,
        )

    def _emit_secrets_audit_log(
        self,
        tenant_id: str,
        platform_name: str,
        correlation_id: str | None,
    ) -> None:
        # See docs/specs/00-shared-contracts.md §C for the audit-log contract.
        # The event key is read by Loki alert rules — do not rename it.
        logger.info(
            "integration_secrets_fetched",
            extra={
                "event": "integration_secrets_fetched",
                "tenant_id": tenant_id,
                "platform_name": platform_name,
                "caller_service": self._service_name,
                "correlation_id": correlation_id or "",
            },
        )
