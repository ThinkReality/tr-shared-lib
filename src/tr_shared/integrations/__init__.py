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
    BAYUT_PLATFORM_NAME,
    DUBIZZLE_PLATFORM_NAME,
    GEMINI_PLATFORM_NAME,
    KNOWN_PF_EVENT_PREFIXES,
    KNOWN_PLATFORM_NAMES,
    PF_API_BASE_URL,
    PF_AUTH_URL,
    PF_PLATFORM_NAME,
    PUBLIC_CONFIG_KEYS,
    sanitize_public_config,
)
from tr_shared.integrations.portal_identity import (
    EXTERNALLY_PUBLISHABLE_SLUGS,
    KNOWN_PLATFORM_SLUGS,
    LISTING_PORTAL_SLUGS,
    PORTAL_PROVIDER_KEYS,
    PORTAL_REGISTRY,
    PORTAL_USER_ID_KEYS,
    PortalIdentity,
    PortalSlug,
    get_portal_identity,
)
from tr_shared.integrations.exceptions import (
    IntegrationConfigError,
    IntegrationConfigNotFound,
)
from tr_shared.integrations.models import IntegrationConfig
from tr_shared.integrations.pf_oauth import fetch_pf_access_token
from tr_shared.integrations.portal_errors import (
    PortalAuthError,
    PortalDuplicateError,
    PortalError,
    PortalNotFoundError,
    PortalRateLimitError,
    PortalServerError,
    PortalUnavailableError,
    PortalValidationError,
)
from tr_shared.integrations.registry import (
    init_integration_config_client,
    get_integration_config_client,
    register_integration_cache_handlers,
    reset_integration_config_client,
)

__all__ = [
    "IntegrationConfigClient",
    "IntegrationConfig",
    "IntegrationConfigError",
    "IntegrationConfigNotFound",
    # Portal error taxonomy (raised by portal adapters; Celery retries on the retryable ones)
    "PortalError",
    "PortalAuthError",
    "PortalValidationError",
    "PortalRateLimitError",
    "PortalDuplicateError",
    "PortalNotFoundError",
    "PortalUnavailableError",
    "PortalServerError",
    # Portal identity (single source of truth — prefer PortalSlug in new code)
    "PortalSlug",
    "PortalIdentity",
    "PORTAL_REGISTRY",
    "get_portal_identity",
    "KNOWN_PLATFORM_SLUGS",
    "LISTING_PORTAL_SLUGS",
    "EXTERNALLY_PUBLISHABLE_SLUGS",
    "PORTAL_USER_ID_KEYS",
    "PORTAL_PROVIDER_KEYS",
    # Platform-name aliases (slug values; legacy — prefer PortalSlug)
    "PF_PLATFORM_NAME",
    "BAYUT_PLATFORM_NAME",
    "DUBIZZLE_PLATFORM_NAME",
    "GEMINI_PLATFORM_NAME",
    "KNOWN_PLATFORM_NAMES",
    "PF_AUTH_URL",
    "PF_API_BASE_URL",
    "ALL_PF_WEBHOOK_EVENTS",
    "KNOWN_PF_EVENT_PREFIXES",
    "PUBLIC_CONFIG_KEYS",
    "fetch_pf_access_token",
    "sanitize_public_config",
    "init_integration_config_client",
    "get_integration_config_client",
    "reset_integration_config_client",
    "register_integration_cache_handlers",
]
