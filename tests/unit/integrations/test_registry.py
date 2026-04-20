"""Tests for the DI registry + event-handler helper."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from tr_shared.events.event_types import AdminEvents
from tr_shared.integrations import (
    IntegrationConfigClient,
    get_integration_config_client,
    init_integration_config_client,
    register_integration_cache_handlers,
    reset_integration_config_client,
)


@dataclass
class _FakeEnvelope:
    tenant_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class _FakeConsumer:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def handler(self, event_type: str):
        def decorator(func):
            self.handlers[event_type] = func
            return func

        return decorator


class _FakeClient:
    def __init__(self) -> None:
        self.invalidations: list[tuple[str | None, str | None]] = []

    def invalidate_cache(
        self,
        tenant_id: str | None = None,
        platform_name: str | None = None,
    ) -> None:
        self.invalidations.append((tenant_id, platform_name))


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    reset_integration_config_client()
    yield
    reset_integration_config_client()


def test_get_raises_when_uninitialized() -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        get_integration_config_client()


def test_init_and_get_roundtrip() -> None:
    client = IntegrationConfigClient(admin_panel_url="http://admin", service_token="t")
    try:
        init_integration_config_client(client)
        assert get_integration_config_client() is client
    finally:
        # __aclose not called here; just drop the HTTP client synchronously
        import asyncio

        asyncio.get_event_loop().run_until_complete(client.close())


def test_reset_clears_registration() -> None:
    client = IntegrationConfigClient(admin_panel_url="http://admin", service_token="t")
    init_integration_config_client(client)
    reset_integration_config_client()
    with pytest.raises(RuntimeError):
        get_integration_config_client()


def test_register_cache_handlers_attaches_three_events() -> None:
    consumer = _FakeConsumer()
    client = _FakeClient()
    register_integration_cache_handlers(consumer, client)  # type: ignore[arg-type]
    assert AdminEvents.INTEGRATION_PLATFORM_CREATED in consumer.handlers
    assert AdminEvents.INTEGRATION_PLATFORM_UPDATED in consumer.handlers
    assert AdminEvents.INTEGRATION_PLATFORM_DELETED in consumer.handlers


@pytest.mark.asyncio
async def test_deleted_handler_invalidates_by_tenant_and_platform() -> None:
    consumer = _FakeConsumer()
    client = _FakeClient()
    register_integration_cache_handlers(consumer, client)  # type: ignore[arg-type]

    envelope = _FakeEnvelope(
        tenant_id="t-1",
        data={
            "tenant_id": "t-1",
            "platform_name": "PropertyFinder API",
            "webhook_token": "wh_xyz",
        },
    )
    await consumer.handlers[AdminEvents.INTEGRATION_PLATFORM_DELETED](envelope)
    assert client.invalidations == [("t-1", "PropertyFinder API")]


@pytest.mark.asyncio
async def test_updated_handler_also_invalidates() -> None:
    consumer = _FakeConsumer()
    client = _FakeClient()
    register_integration_cache_handlers(consumer, client)  # type: ignore[arg-type]

    envelope = _FakeEnvelope(
        tenant_id="t-2",
        data={"tenant_id": "t-2", "platform_name": "PropertyFinder API"},
    )
    await consumer.handlers[AdminEvents.INTEGRATION_PLATFORM_UPDATED](envelope)
    assert client.invalidations == [("t-2", "PropertyFinder API")]


@pytest.mark.asyncio
async def test_created_handler_invalidates_too() -> None:
    """CREATED invalidates to catch the unlikely case where a stale entry exists
    (e.g. dedup loser re-created after soft-delete)."""
    consumer = _FakeConsumer()
    client = _FakeClient()
    register_integration_cache_handlers(consumer, client)  # type: ignore[arg-type]

    envelope = _FakeEnvelope(
        tenant_id="t-3",
        data={"tenant_id": "t-3", "platform_name": "PropertyFinder API"},
    )
    await consumer.handlers[AdminEvents.INTEGRATION_PLATFORM_CREATED](envelope)
    assert client.invalidations == [("t-3", "PropertyFinder API")]


@pytest.mark.asyncio
async def test_handler_swallows_exception() -> None:
    """A broken invalidate_cache must not crash the consumer loop."""

    class _ExplodingClient:
        def invalidate_cache(self, **_kw: Any) -> None:
            raise RuntimeError("simulated")

    consumer = _FakeConsumer()
    register_integration_cache_handlers(consumer, _ExplodingClient())  # type: ignore[arg-type]
    envelope = _FakeEnvelope(tenant_id="t", data={"tenant_id": "t"})
    # Must not raise
    await consumer.handlers[AdminEvents.INTEGRATION_PLATFORM_DELETED](envelope)


@pytest.mark.asyncio
async def test_handler_falls_back_to_envelope_tenant_id() -> None:
    """When data dict omits tenant_id, fall back to envelope.tenant_id."""
    consumer = _FakeConsumer()
    client = _FakeClient()
    register_integration_cache_handlers(consumer, client)  # type: ignore[arg-type]

    envelope = _FakeEnvelope(tenant_id="env-tenant", data={})
    await consumer.handlers[AdminEvents.INTEGRATION_PLATFORM_DELETED](envelope)
    assert client.invalidations == [("env-tenant", None)]
