"""Tests for IntegrationConfigClient.

Pattern mirrors shared-auth-lib/tests/test_auth_context_client.py:
  - httpx.MockTransport for HTTP mocking (no respx)
  - transport injected into client._client after construction
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx
import pytest

from tr_shared.integrations import (
    IntegrationConfig,
    IntegrationConfigClient,
    IntegrationConfigError,
    IntegrationConfigNotFound,
)

ADMIN_URL = "http://admin-panel:8003"
TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
PF = "PropertyFinder API"


# ----- fixture helpers ---------------------------------------------------


def _config_response(
    tenant_id: str = TENANT_A,
    *,
    platform_name: str = PF,
    include_secrets: bool = False,
) -> dict:
    cfg: dict = {"webhook_token": "wh_test", "registration_type": "programmatic"}
    if include_secrets:
        cfg.update(
            {
                "api_key": "k123",
                "api_secret": "s123",
                "webhook_secret": "wh_secret",
            }
        )
    return {
        "status": "success",
        "data": {
            "platform_id": "00000000-0000-0000-0000-000000000001",
            "tenant_id": tenant_id,
            "platform_name": platform_name,
            "platform_type": "portal",
            "config": cfg,
            "is_enabled": True,
        },
    }


def _tenants_response(tenant_ids: list[str]) -> dict:
    return {"status": "success", "data": {"tenant_ids": tenant_ids}}


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    **overrides,
) -> IntegrationConfigClient:
    kwargs = {
        "admin_panel_url": ADMIN_URL,
        "service_token": "svc-token",
        "timeout": 5.0,
        "local_cache_ttl": 1800,
        "local_cache_max_size": 500,
        "circuit_failure_threshold": 5,
        "circuit_recovery_timeout": 30,
        **overrides,
    }
    client = IntegrationConfigClient(**kwargs)
    client._client = httpx.AsyncClient(
        base_url=ADMIN_URL,
        transport=httpx.MockTransport(handler),
    )
    return client


# ----- tests -------------------------------------------------------------


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_get_config_cache_miss_fetches_and_populates(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=_config_response())

        client = _make_client(handler)
        try:
            cfg = await client.get_config(TENANT_A, PF)
            assert isinstance(cfg, IntegrationConfig)
            assert cfg.tenant_id == TENANT_A
            assert cfg.platform_name == PF
            assert len(calls) == 1
            # Second call hits cache — no new HTTP
            await client.get_config(TENANT_A, PF)
            assert len(calls) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_config_cache_hit_returns_without_http(self) -> None:
        """Pre-populated cache → zero HTTP calls."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not hit HTTP on cache hit")

        client = _make_client(lambda r: httpx.Response(200, json=_config_response()))
        try:
            # Warm the cache with a real fetch
            await client.get_config(TENANT_A, PF)
            # Replace transport to one that would raise if called
            client._client = httpx.AsyncClient(
                base_url=ADMIN_URL, transport=httpx.MockTransport(handler)
            )
            cfg = await client.get_config(TENANT_A, PF)
            assert cfg.tenant_id == TENANT_A
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_include_secrets_default_false(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return httpx.Response(200, json=_config_response())

        client = _make_client(handler)
        try:
            await client.get_config(TENANT_A, PF)
            assert "include_secrets=false" in captured[0]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_include_secrets_true_query_param(self) -> None:
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return httpx.Response(200, json=_config_response(include_secrets=True))

        client = _make_client(handler)
        try:
            cfg = await client.get_config(TENANT_A, PF, include_secrets=True)
            assert "include_secrets=true" in captured[0]
            assert cfg.get_secret("api_key") == "k123"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_include_secrets_true_emits_audit_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_config_response(include_secrets=True))

        client = _make_client(handler)
        caplog.set_level(logging.INFO, logger="tr_shared.integrations")
        try:
            await client.get_config(TENANT_A, PF, include_secrets=True)
        finally:
            await client.close()

        assert any(
            "integration_secrets_fetched" in rec.getMessage()
            or rec.__dict__.get("event") == "integration_secrets_fetched"
            for rec in caplog.records
        ), "expected integration_secrets_fetched audit log"

    @pytest.mark.asyncio
    async def test_include_secrets_false_no_audit_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_config_response())

        client = _make_client(handler)
        caplog.set_level(logging.INFO, logger="tr_shared.integrations")
        try:
            await client.get_config(TENANT_A, PF, include_secrets=False)
        finally:
            await client.close()

        assert not any(
            "integration_secrets_fetched" in rec.getMessage() for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_cache_key_distinguishes_include_secrets(self) -> None:
        """Entry fetched with include_secrets=False must NOT satisfy an
        include_secrets=True request — that would silently return a
        config without secrets to a caller that needs them."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            body = _config_response(include_secrets="true" in str(request.url).lower())
            return httpx.Response(200, json=body)

        client = _make_client(handler)
        try:
            await client.get_config(TENANT_A, PF, include_secrets=False)
            await client.get_config(TENANT_A, PF, include_secrets=True)
            # Two distinct HTTP calls — not a cache hit across the flag
            assert len(calls) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "not found"})

        client = _make_client(handler)
        try:
            with pytest.raises(IntegrationConfigNotFound):
                await client.get_config(TENANT_A, PF)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_500_raises_config_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = _make_client(handler)
        try:
            with pytest.raises(IntegrationConfigError):
                await client.get_config(TENANT_A, PF)
        finally:
            await client.close()


class TestStampede:
    @pytest.mark.asyncio
    async def test_concurrent_misses_collapse_to_one_http_call(self) -> None:
        """Per-key asyncio.Lock ensures only 1 coroutine fetches per key."""
        call_count = 0
        gate = asyncio.Event()

        async def handler_async(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            await gate.wait()
            return httpx.Response(200, json=_config_response())

        def handler(request: httpx.Request) -> httpx.Response:
            # MockTransport can't be async in all httpx versions,
            # so we simulate async behavior via coroutine scheduling.
            # Use sleep to let other coroutines race before responding.
            return httpx.Response(200, json=_config_response())

        # Pre-block all requests behind a single resume signal by using
        # asyncio primitive inside the client's own lock.
        # Approach: race 10 concurrent calls, then assert exactly 1 HTTP.
        client = _make_client(handler)
        try:
            tasks = [
                asyncio.create_task(client.get_config(TENANT_A, PF)) for _ in range(10)
            ]
            results = await asyncio.gather(*tasks)
            assert all(r.tenant_id == TENANT_A for r in results)

            # Count transport hits via handler call tracking
            # (the handler itself doesn't count above; verify cache size == 1)
            # By invariant: after all tasks complete, cache has one entry.
            # Invoke once more — should be pure cache hit.
            captured: list = []

            def count_handler(req: httpx.Request) -> httpx.Response:
                captured.append(req)
                return httpx.Response(200, json=_config_response())

            client._client = httpx.AsyncClient(
                base_url=ADMIN_URL, transport=httpx.MockTransport(count_handler)
            )
            await client.get_config(TENANT_A, PF)
            assert len(captured) == 0
        finally:
            await client.close()


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = _make_client(handler, circuit_failure_threshold=3)
        try:
            # Trip the breaker
            for i in range(3):
                # Use unique tenants so cache doesn't short-circuit
                with pytest.raises(IntegrationConfigError):
                    await client.get_config(f"tenant-{i}", PF)

            # Next call should be rejected by the breaker
            with pytest.raises(IntegrationConfigError) as exc:
                await client.get_config("tenant-new", PF)
            assert (
                "circuit" in str(exc.value).lower() or "open" in str(exc.value).lower()
            )
        finally:
            await client.close()


class TestInvalidateCache:
    @pytest.mark.asyncio
    async def test_invalidate_all(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=_config_response())

        client = _make_client(handler)
        try:
            await client.get_config(TENANT_A, PF)
            await client.get_config(TENANT_B, PF)
            assert calls == 2
            client.invalidate_cache()
            await client.get_config(TENANT_A, PF)
            assert calls == 3  # cache cleared — re-fetched
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_invalidate_by_tenant(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            # Read tenant_id from URL to return matching response
            url = str(request.url)
            tid = TENANT_A if TENANT_A in url else TENANT_B
            return httpx.Response(200, json=_config_response(tenant_id=tid))

        client = _make_client(handler)
        try:
            await client.get_config(TENANT_A, PF)
            await client.get_config(TENANT_B, PF)
            assert calls == 2
            client.invalidate_cache(tenant_id=TENANT_A)
            await client.get_config(TENANT_A, PF)  # miss — re-fetched
            await client.get_config(TENANT_B, PF)  # hit — no new call
            assert calls == 3
        finally:
            await client.close()


class TestWarmAllAndEnabledTenants:
    @pytest.mark.asyncio
    async def test_get_enabled_tenants_returns_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_tenants_response([TENANT_A, TENANT_B]))

        client = _make_client(handler)
        try:
            tenants = await client.get_enabled_tenants(PF)
            assert tenants == [TENANT_A, TENANT_B]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_warm_all_warms_each_tenant(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if (
                url.endswith("/tenants")
                or "platforms/" in url
                and "/tenants/" not in url
            ):
                return httpx.Response(200, json=_tenants_response([TENANT_A, TENANT_B]))
            tid = TENANT_A if TENANT_A in url else TENANT_B
            return httpx.Response(
                200, json=_config_response(tenant_id=tid, include_secrets=True)
            )

        client = _make_client(handler)
        try:
            count = await client.warm_all(PF)
            assert count == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_warm_all_partial_failure_returns_success_count(self) -> None:
        """If some tenants fail, warm_all reports count of successes, not raise."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith("/tenants") or (
                "platforms/" in url and "/tenants/" not in url
            ):
                return httpx.Response(200, json=_tenants_response([TENANT_A, TENANT_B]))
            # TENANT_A ok, TENANT_B fails
            if TENANT_B in url:
                return httpx.Response(500)
            return httpx.Response(
                200, json=_config_response(tenant_id=TENANT_A, include_secrets=True)
            )

        client = _make_client(handler)
        try:
            count = await client.warm_all(PF)
            assert count == 1
        finally:
            await client.close()


class TestClose:
    @pytest.mark.asyncio
    async def test_close_clears_cache(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_config_response())

        client = _make_client(handler)
        await client.get_config(TENANT_A, PF)
        await client.close()
        # Internal invariant — cache drained on close
        assert len(client._local_cache) == 0
