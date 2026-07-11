"""Single source of truth for portal / integration-platform identity.

Every service identifies a portal by its **slug** — the lowercase token stored
in ``admin.admin_panel_listing_platform_configs.platform_name``, used as the
listing ``PortalName`` value, the webhook provider-routing key, and the
``users.portal_info`` JSONB key. There is exactly one vocabulary.

One :class:`PortalIdentity` per portal carries every per-portal fact, so the
slug, display name, ``portal_info`` user-id key, connectable-platform flag, and
listing-target flag can never drift apart across services. Derived collections
(:data:`KNOWN_PLATFORM_SLUGS`, :data:`LISTING_PORTAL_SLUGS`,
:data:`PORTAL_USER_ID_KEYS`, :data:`PORTAL_PROVIDER_KEYS`) are **computed** from
the registry — change a fact in one place.

Extending: add a :class:`PortalSlug` member + a :data:`PORTAL_REGISTRY` entry. A
new *connectable platform* also requires a data migration + CHECK-constraint
regen on ``admin.admin_panel_listing_platform_configs`` (the constraint is
generated from :data:`KNOWN_PLATFORM_SLUGS`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class PortalSlug(StrEnum):
    """Canonical portal/platform identifier — the one ID used everywhere.

    Stored verbatim in ``admin_panel_listing_platform_configs.platform_name``
    and used as the listing ``PortalName`` value. Lowercase, no spaces.
    """

    WEBSITE = "website"
    PROPERTYFINDER = "propertyfinder"
    BAYUT = "bayut"
    DUBIZZLE = "dubizzle"
    GEMINI = "gemini"
    META = "meta"


@dataclass(frozen=True, slots=True)
class PortalIdentity:
    """All per-portal facts in one immutable record.

    Attributes:
        slug: Canonical identifier (see :class:`PortalSlug`).
        display_name: Human-facing label for UI / logs.
        is_connectable_platform: Tenant connects credentials via admin panel
            and the row is stored in ``admin_panel_listing_platform_configs``
            (PropertyFinder, Bayut, Dubizzle, Gemini). ``website`` is internal,
            so ``False``.
        is_listing_portal: Appears as a listing publish target
            (``website`` + the three external portals). Gemini is ``False``.
        is_externally_publishable: Can be published/unpublished on an external
            portal API. ``website`` is internal → ``False``.
        user_id_key: Key under ``users.portal_info[slug]`` that holds this
            portal's agent id (PF → ``public_profile_id``; Bayut/Dubizzle →
            ``user_id``). ``None`` when the portal has no agent mapping.
        shares_provider_with: When set, this portal is served by another
            portal's upstream provider (Dubizzle is served by Bayut/Profolio),
            so webhook/provider routing keys off the shared provider.
    """

    slug: PortalSlug
    display_name: str
    is_connectable_platform: bool
    is_listing_portal: bool
    is_externally_publishable: bool
    user_id_key: str | None = None
    shares_provider_with: PortalSlug | None = None

    @property
    def provider_key(self) -> str:
        """Webhook/provider routing key.

        A portal that shares another portal's provider routes under that
        provider's slug (Dubizzle → ``bayut``); otherwise its own slug.
        """
        return (self.shares_provider_with or self.slug).value


PORTAL_REGISTRY: Final[dict[PortalSlug, PortalIdentity]] = {
    PortalSlug.WEBSITE: PortalIdentity(
        slug=PortalSlug.WEBSITE,
        display_name="Website",
        is_connectable_platform=False,
        is_listing_portal=True,
        is_externally_publishable=False,
    ),
    PortalSlug.PROPERTYFINDER: PortalIdentity(
        slug=PortalSlug.PROPERTYFINDER,
        display_name="PropertyFinder",
        is_connectable_platform=True,
        is_listing_portal=True,
        is_externally_publishable=True,
        user_id_key="public_profile_id",
    ),
    PortalSlug.BAYUT: PortalIdentity(
        slug=PortalSlug.BAYUT,
        display_name="Bayut",
        is_connectable_platform=True,
        is_listing_portal=True,
        is_externally_publishable=True,
        user_id_key="user_id",
    ),
    PortalSlug.DUBIZZLE: PortalIdentity(
        slug=PortalSlug.DUBIZZLE,
        display_name="Dubizzle",
        is_connectable_platform=True,
        is_listing_portal=True,
        is_externally_publishable=True,
        user_id_key="user_id",
        shares_provider_with=PortalSlug.BAYUT,
    ),
    PortalSlug.GEMINI: PortalIdentity(
        slug=PortalSlug.GEMINI,
        display_name="Google Gemini AI",
        is_connectable_platform=True,
        is_listing_portal=False,
        is_externally_publishable=False,
    ),
    PortalSlug.META: PortalIdentity(
        slug=PortalSlug.META,
        display_name="Meta",
        is_connectable_platform=False,
        is_listing_portal=False,
        is_externally_publishable=False,
    ),
}


def get_portal_identity(slug: str | PortalSlug) -> PortalIdentity:
    """Return the :class:`PortalIdentity` for ``slug``.

    Raises:
        ValueError: If ``slug`` is not a known :class:`PortalSlug`.
    """
    return PORTAL_REGISTRY[PortalSlug(slug)]


KNOWN_PLATFORM_SLUGS: Final[frozenset[str]] = frozenset(
    p.slug.value for p in PORTAL_REGISTRY.values() if p.is_connectable_platform
)
"""Every ``platform_name`` the admin panel manages. The admin CHECK constraint
``admin_panel_listing_platform_configs.ck_platform_name_known`` MUST be
generated from this set — keeps DB and shared lib impossible to drift."""

LISTING_PORTAL_SLUGS: Final[frozenset[str]] = frozenset(
    p.slug.value for p in PORTAL_REGISTRY.values() if p.is_listing_portal
)
"""Slugs that are valid listing publish targets (website + external portals)."""

EXTERNALLY_PUBLISHABLE_SLUGS: Final[frozenset[str]] = frozenset(
    p.slug.value for p in PORTAL_REGISTRY.values() if p.is_externally_publishable
)
"""Slugs that can be published/unpublished on an external portal API."""

PORTAL_USER_ID_KEYS: Final[dict[str, str]] = {
    p.slug.value: p.user_id_key
    for p in PORTAL_REGISTRY.values()
    if p.user_id_key is not None
}
"""``slug -> portal_info[slug] agent-id key`` (PF ``public_profile_id``,
Bayut/Dubizzle ``user_id``). The one place this mapping is defined."""

PORTAL_PROVIDER_KEYS: Final[dict[str, str]] = {
    p.slug.value: p.provider_key
    for p in PORTAL_REGISTRY.values()
    if p.is_connectable_platform
}
"""``slug -> webhook/provider routing key`` (Dubizzle routes under ``bayut``)."""
