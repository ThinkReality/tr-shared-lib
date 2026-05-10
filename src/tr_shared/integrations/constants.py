"""Canonical constants for third-party integration platforms.

Extending these requires a coordinated change across tr-be-admin-panel,
tr-listing-service, and (where applicable) a migration to update the
admin.admin_panel_listing_platform_configs.ck_platform_name_known CHECK
constraint. See docs/specs/00-shared-contracts.md §A.
"""

from typing import Any, Final

# PropertyFinder ---------------------------------------------------------

PF_PLATFORM_NAME: Final[str] = "PropertyFinder API"
"""Canonical platform_name string used in admin.admin_panel_listing_platform_configs.
Must exactly match the value written by admin-panel's connect_propertyfinder()."""

PF_AUTH_URL: Final[str] = "https://atlas.propertyfinder.com/v1/auth/token"
"""PropertyFinder Atlas token endpoint. Non-standard protocol — accepts
JSON body {apiKey, apiSecret}, returns {accessToken, expiresIn}."""

PF_API_BASE_URL: Final[str] = "https://atlas.propertyfinder.com"
"""PropertyFinder Atlas REST API base URL (webhooks, leads, listings)."""

ALL_PF_WEBHOOK_EVENTS: Final[tuple[str, ...]] = (
    "lead.created",
    "lead.updated",
    "lead.assigned",
    "listing.published",
    "listing.unpublished",
    "listing.action",
    "user.created",
    "user.updated",
    "user.deleted",
    "user.activated",
    "user.deactivated",
    "publicProfile.verification.approved",
    "publicProfile.verification.rejected",
)
"""All 13 PF webhook event IDs — registered in this order by the admin-panel
PropertyFinderRegistrar during connect_propertyfinder()."""

KNOWN_PF_EVENT_PREFIXES: Final[frozenset[str]] = frozenset(
    {"lead.", "listing.", "user.", "publicProfile."}
)
"""Event-prefix set for the tr-api-gateway PROVIDER_EVENT_ROUTING invariant
tests. A typo in gateway routing (e.g., "leads." with extra s) is caught
by comparing configured prefixes against this set."""

# Google Gemini ---------------------------------------------------------

GEMINI_PLATFORM_NAME: Final[str] = "Google Gemini AI"
"""Canonical platform_name string for the Google Gemini API integration
stored alongside real portal integrations in admin_panel_listing_platform_configs."""


# Bayut / Dubizzle ------------------------------------------------------

BAYUT_PLATFORM_NAME: Final[str] = "Bayut API"
"""Canonical platform_name string for the Bayut Profolio API (pull leads
+ push webhooks). Admin enters a static Bearer token via the admin-panel
connect endpoint; the Vault payload is ``{"api_token": "..."}``."""

DUBIZZLE_PLATFORM_NAME: Final[str] = "Dubizzle API"
"""Canonical platform_name string for the Dubizzle Profolio API. Same
underlying api.bayut.com endpoint and same auth scheme as Bayut, registered
separately so admin can manage the two portals independently."""


# Platform registry ------------------------------------------------------

KNOWN_PLATFORM_NAMES: Final[frozenset[str]] = frozenset(
    {
        PF_PLATFORM_NAME,
        GEMINI_PLATFORM_NAME,
        BAYUT_PLATFORM_NAME,
        DUBIZZLE_PLATFORM_NAME,
    },
)
"""Superset of all platform_name values the admin panel manages today.
The admin-panel CHECK constraint (admin.admin_panel_listing_platform_configs
.ck_platform_name_known) MUST be generated from this frozenset — keeps DB
and shared lib impossible to drift. See 01-batch-foundation.md §1B."""


# Public (non-secret) config allowlist -----------------------------------

PUBLIC_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "webhook_token",
        "environment",
        "region",
        "auto_publish",
        "registration_type",
        "connected_at",
        "subscription_count",
    },
)
"""Keys allowed to appear in platform config dicts returned to non-secret
consumers. Every key NOT on this list is redacted by ``sanitize_public_config``.
Allowlist (not blocklist) so a new sensitive key added later is redacted by
default — no future "secret leaked because the blocklist didn't list it" bugs."""


def sanitize_public_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``config`` with only PUBLIC_CONFIG_KEYS retained.

    Use in every code path that returns integration config to a non-privileged
    caller (S2S endpoints with include_secrets=False, admin API responses,
    audit log export, etc.).

    Args:
        config: Platform config dict (or None).

    Returns:
        Empty dict if ``config`` is None or empty; otherwise a new dict
        containing only keys present in ``PUBLIC_CONFIG_KEYS``.
    """
    if not config:
        return {}
    return {k: v for k, v in config.items() if k in PUBLIC_CONFIG_KEYS}
