"""DI registry for IntegrationConfigClient.

The registry pattern mirrors shared-auth-lib's _AuthClientRegistry
(see shared-auth-lib/shared_auth_lib/dependencies/auth_dependencies.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tr_shared.integrations.config_client import IntegrationConfigClient


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
