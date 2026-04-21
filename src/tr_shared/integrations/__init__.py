"""Integration configuration client + shared constants for ThinkRealty.

This package provides a standardized way for services to fetch per-tenant
third-party integration configuration (API keys, webhook secrets, etc.)
from the admin panel. Credentials are kept in Supabase Vault — admin
panel is the single source of truth — and this client caches results
in-memory with event-driven invalidation via tr_event_bus.

See docs/specs/01-batch-foundation.md for the full spec.
"""

from tr_shared.integrations.config_client import IntegrationConfigClient
from tr_shared.integrations.constants import (
    ALL_PF_WEBHOOK_EVENTS,
    GEMINI_PLATFORM_NAME,
    KNOWN_PF_EVENT_PREFIXES,
    KNOWN_PLATFORM_NAMES,
    PF_API_BASE_URL,
    PF_AUTH_URL,
    PF_PLATFORM_NAME,
    PUBLIC_CONFIG_KEYS,
    sanitize_public_config,
)
from tr_shared.integrations.exceptions import (
    IntegrationConfigError,
    IntegrationConfigNotFound,
)
from tr_shared.integrations.models import IntegrationConfig
from tr_shared.integrations.pf_oauth import fetch_pf_access_token
from tr_shared.integrations.registry import (
    init_integration_config_client,
    get_integration_config_client,
    register_integration_cache_handlers,
    reset_integration_config_client,
)

__all__ = [
    # Client
    "IntegrationConfigClient",
    # Model
    "IntegrationConfig",
    # Exceptions
    "IntegrationConfigError",
    "IntegrationConfigNotFound",
    # Constants
    "PF_PLATFORM_NAME",
    "PF_AUTH_URL",
    "PF_API_BASE_URL",
    "GEMINI_PLATFORM_NAME",
    "KNOWN_PLATFORM_NAMES",
    "ALL_PF_WEBHOOK_EVENTS",
    "KNOWN_PF_EVENT_PREFIXES",
    "PUBLIC_CONFIG_KEYS",
    # Helpers
    "fetch_pf_access_token",
    "sanitize_public_config",
    # DI registry
    "init_integration_config_client",
    "get_integration_config_client",
    "reset_integration_config_client",
    "register_integration_cache_handlers",
]
