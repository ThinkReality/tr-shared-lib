"""Canonical constants for third-party integration platforms.

Extending these requires a coordinated change across tr-be-admin-panel,
tr-listing-service, and (where applicable) a migration to update the
admin.admin_panel_listing_platform_configs.ck_platform_name_known CHECK
constraint. See docs/specs/00-shared-contracts.md §A.
"""

from typing import Final

# PropertyFinder ---------------------------------------------------------

PF_PLATFORM_NAME: Final[str] = "PropertyFinder API"
"""Canonical platform_name string used in admin.admin_panel_listing_platform_configs.
Must exactly match the value written by admin-panel's connect_propertyfinder()."""

PF_AUTH_URL: Final[str] = "https://auth.propertyfinder.com/auth/oauth/v1/token"
"""OAuth2 client-credentials token endpoint."""

PF_API_BASE_URL: Final[str] = "https://api.propertyfinder.com"
"""PropertyFinder REST API base URL (webhooks, leads, listings)."""

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

# Platform registry ------------------------------------------------------

KNOWN_PLATFORM_NAMES: Final[frozenset[str]] = frozenset({PF_PLATFORM_NAME})
"""Superset of all platform_name values the admin panel manages today.
Adding Bayut/Meta/etc. requires an Alembic migration to extend the
ck_platform_name_known CHECK constraint — see 01-batch-foundation.md §1B."""
