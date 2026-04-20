"""DI registry and event-handler helper for IntegrationConfigClient.

The registry pattern mirrors shared-auth-lib's _AuthClientRegistry
(see shared-auth-lib/shared_auth_lib/dependencies/auth_dependencies.py).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tr_shared.events.event_types import AdminEvents

if TYPE_CHECKING:
    from tr_shared.events.consumer import EventConsumer
    from tr_shared.events.envelope import EventEnvelope
    from tr_shared.integrations.config_client import IntegrationConfigClient

logger = logging.getLogger("tr_shared.integrations")


class _IntegrationClientRegistry:
    """Class-level singleton registry for the IntegrationConfigClient."""

    _client: "IntegrationConfigClient | None" = None

    @classmethod
    def set(cls, client: "IntegrationConfigClient") -> None:
        cls._client = client

    @classmethod
    def get(cls) -> "IntegrationConfigClient":
        if cls._client is None:
            raise RuntimeError(
                "IntegrationConfigClient not initialized. "
                "Call init_integration_config_client() during app startup."
            )
        return cls._client

    @classmethod
    def reset(cls) -> None:
        """Reset the registry — use only in tests or on app shutdown."""
        cls._client = None


def init_integration_config_client(client: "IntegrationConfigClient") -> None:
    """Initialize the process-global IntegrationConfigClient.

    Call once during application startup (lifespan). Subsequent calls
    overwrite the registered client.
    """
    _IntegrationClientRegistry.set(client)


def get_integration_config_client() -> "IntegrationConfigClient":
    """Return the initialized IntegrationConfigClient.

    Raises RuntimeError if init_integration_config_client() was not called.
    """
    return _IntegrationClientRegistry.get()


def reset_integration_config_client() -> None:
    """Clear the registered client — use in tests and on app shutdown."""
    _IntegrationClientRegistry.reset()


def register_integration_cache_handlers(
    consumer: "EventConsumer",
    client: "IntegrationConfigClient",
) -> None:
    """Register AdminEvents cache-invalidation handlers on an EventConsumer.

    Subscribes to INTEGRATION_PLATFORM_{CREATED,UPDATED,DELETED} and
    invalidates the client's local cache for the affected (tenant_id,
    platform_name). CREATED/UPDATED events pre-warm implicitly via the
    next on-demand fetch; no explicit warm call here to avoid S2S calls
    inside an event handler.

    Handlers swallow exceptions locally after logging — a broken cache
    invalidation must not crash the event consumer. The 1800s TTL caps
    the blast radius if invalidation is missed.
    """

    @consumer.handler(AdminEvents.INTEGRATION_PLATFORM_CREATED)
    async def _on_created(envelope: "EventEnvelope") -> None:
        _invalidate_for_event(client, envelope, "CREATED")

    @consumer.handler(AdminEvents.INTEGRATION_PLATFORM_UPDATED)
    async def _on_updated(envelope: "EventEnvelope") -> None:
        _invalidate_for_event(client, envelope, "UPDATED")

    @consumer.handler(AdminEvents.INTEGRATION_PLATFORM_DELETED)
    async def _on_deleted(envelope: "EventEnvelope") -> None:
        _invalidate_for_event(client, envelope, "DELETED")


def _invalidate_for_event(
    client: "IntegrationConfigClient",
    envelope: "EventEnvelope",
    event_kind: str,
) -> None:
    try:
        tenant_id = envelope.data.get("tenant_id") or envelope.tenant_id or None
        platform_name = envelope.data.get("platform_name") or None
        client.invalidate_cache(tenant_id=tenant_id, platform_name=platform_name)
        logger.info(
            "integration_cache_invalidated",
            extra={
                "event_kind": event_kind,
                "tenant_id": tenant_id,
                "platform_name": platform_name,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "integration_cache_invalidation_failed",
            extra={"event_kind": event_kind, "error": str(exc)},
        )
