"""Tests for the IntegrationConfigClient DI registry."""

import asyncio

import pytest

from tr_shared.integrations import (
    IntegrationConfigClient,
    get_integration_config_client,
    init_integration_config_client,
    reset_integration_config_client,
)


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
        # Own loop, not the ambient one. `asyncio.get_event_loop()` returns
        # whatever loop the process last set as current — which another test in
        # the same session may already have closed.
        asyncio.run(client.close())


def test_reset_clears_registration() -> None:
    client = IntegrationConfigClient(admin_panel_url="http://admin", service_token="t")
    init_integration_config_client(client)
    reset_integration_config_client()
    with pytest.raises(RuntimeError):
        get_integration_config_client()
