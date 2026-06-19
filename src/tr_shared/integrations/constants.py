"""Canonical constants for third-party integration platforms.

Portal **identity** (slug, display name, user-id key, platform registry) lives in
:mod:`tr_shared.integrations.portal_identity` — the single source of truth. The
``*_PLATFORM_NAME`` aliases and :data:`KNOWN_PLATFORM_NAMES` below are thin
re-exports of that registry's slug values, kept so existing imports keep working;
prefer :class:`~tr_shared.integrations.portal_identity.PortalSlug` in new code.

PropertyFinder transport constants (auth/base URL, webhook event ids) stay here —
they are PF-specific protocol detail, not identity. Changing a connectable
platform requires a data migration + CHECK-constraint regen on
admin.admin_panel_listing_platform_configs (generated from KNOWN_PLATFORM_NAMES).
"""

from typing import Any, Final

from tr_shared.integrations.portal_identity import KNOWN_PLATFORM_SLUGS, PortalSlug

# Platform-name aliases (slug values; prefer PortalSlug in new code) ------

PF_PLATFORM_NAME: Final[str] = PortalSlug.PROPERTYFINDER.value
"""Canonical platform_name (slug) in admin.admin_panel_listing_platform_configs.
Equals the value written by admin's connect_propertyfinder(). Legacy alias of
``PortalSlug.PROPERTYFINDER``."""

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

GEMINI_PLATFORM_NAME: Final[str] = PortalSlug.GEMINI.value
"""platform_name (slug) for the Google Gemini API integration stored alongside
real portal integrations. Legacy alias of ``PortalSlug.GEMINI``."""


# Bayut / Dubizzle ------------------------------------------------------

BAYUT_PLATFORM_NAME: Final[str] = PortalSlug.BAYUT.value
"""platform_name (slug) for the Bayut Profolio API (pull leads + push webhooks).
Admin enters a static Bearer token; Vault payload ``{"api_token": "..."}``.
Legacy alias of ``PortalSlug.BAYUT``."""

DUBIZZLE_PLATFORM_NAME: Final[str] = PortalSlug.DUBIZZLE.value
"""platform_name (slug) for the Dubizzle Profolio API. Same upstream provider
and auth scheme as Bayut, managed separately. Legacy alias of
``PortalSlug.DUBIZZLE``."""


# Platform registry ------------------------------------------------------

KNOWN_PLATFORM_NAMES: Final[frozenset[str]] = KNOWN_PLATFORM_SLUGS
"""All platform_name (slug) values the admin panel manages. Derived from
:data:`tr_shared.integrations.portal_identity.PORTAL_REGISTRY`. The admin CHECK
constraint (admin.admin_panel_listing_platform_configs.ck_platform_name_known)
MUST be generated from this set — keeps DB and shared lib impossible to drift."""


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
