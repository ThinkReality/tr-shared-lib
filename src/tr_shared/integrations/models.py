"""Data models for the integrations package."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class IntegrationConfig(BaseModel):
    """Immutable per-tenant integration configuration.

    Returned by IntegrationConfigClient.get_config(). When the client
    was called with include_secrets=False (the default), the `config`
    dict contains only non-sensitive JSONB fields from the admin panel.
    When include_secrets=True, `config` also includes the Vault-decrypted
    secrets (api_key, api_secret, webhook_secret) merged in.
    """

    model_config = ConfigDict(frozen=True)

    platform_id: str
    tenant_id: str
    platform_name: str
    platform_type: str
    config: dict[str, Any]
    is_enabled: bool

    def get_secret(self, key: str, default: str = "") -> str:
        """Read a secret (or any) key from the config dict as a string.

        Returns `default` when the key is absent or has a None value.
        Callers MUST have fetched this config with include_secrets=True
        to rely on secret keys; otherwise they will always be absent.
        """
        value = self.config.get(key, default)
        if value is None:
            return default
        return str(value)
