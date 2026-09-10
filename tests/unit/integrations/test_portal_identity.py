"""Portal identity registry is the single source of truth — guard its invariants."""

from tr_shared.integrations import portal_identity as P
from tr_shared.integrations.portal_identity import PortalSlug


def test_every_slug_has_a_registry_entry() -> None:
    assert set(P.PORTAL_REGISTRY) == set(PortalSlug)


def test_registry_entry_slug_matches_key() -> None:
    for slug, identity in P.PORTAL_REGISTRY.items():
        assert identity.slug is slug


def test_all_slugs_are_lowercase_no_spaces() -> None:
    for slug in PortalSlug:
        assert slug.value == slug.value.lower()
        assert " " not in slug.value


def test_known_platform_slugs_are_the_connectable_platforms() -> None:
    assert P.KNOWN_PLATFORM_SLUGS == frozenset(
        {"propertyfinder", "bayut", "dubizzle", "gemini", "hikcentral", "calcom"},
    )
    assert "website" not in P.KNOWN_PLATFORM_SLUGS


def test_listing_portal_slugs_exclude_gemini_include_website() -> None:
    assert P.LISTING_PORTAL_SLUGS == frozenset(
        {"website", "propertyfinder", "bayut", "dubizzle"},
    )
    assert "gemini" not in P.LISTING_PORTAL_SLUGS


def test_externally_publishable_excludes_website_and_gemini() -> None:
    assert P.EXTERNALLY_PUBLISHABLE_SLUGS == frozenset(
        {"propertyfinder", "bayut", "dubizzle"},
    )


def test_meta_is_webhook_only_lead_portal() -> None:
    # Meta (Facebook lead ads) is lead-source only — no listing/connect/publish flags.
    meta = P.PORTAL_REGISTRY[PortalSlug.META]
    assert meta.slug is PortalSlug.META
    assert meta.display_name == "Meta (Facebook Lead Ads)"
    assert meta.is_connectable_platform is False
    assert meta.is_listing_portal is False
    assert meta.is_externally_publishable is False
    assert meta.user_id_key is None
    assert "meta" not in P.KNOWN_PLATFORM_SLUGS
    assert "meta" not in P.LISTING_PORTAL_SLUGS


def test_hikcentral_is_connectable_non_listing_platform() -> None:
    hikcentral = P.PORTAL_REGISTRY[PortalSlug.HIKCENTRAL]
    assert hikcentral.slug is PortalSlug.HIKCENTRAL
    assert hikcentral.display_name == "HikCentral"
    assert hikcentral.is_connectable_platform is True
    assert hikcentral.is_listing_portal is False
    assert hikcentral.is_externally_publishable is False
    assert hikcentral.user_id_key is None
    assert "hikcentral" in P.KNOWN_PLATFORM_SLUGS
    assert "hikcentral" not in P.LISTING_PORTAL_SLUGS
    assert "hikcentral" not in P.EXTERNALLY_PUBLISHABLE_SLUGS


def test_calcom_is_connectable_non_listing_platform() -> None:
    """Same shape as HikCentral: a tenant connects credentials, but nothing is ever
    published to it, so it must stay out of the listing and publish collections."""
    calcom = P.PORTAL_REGISTRY[PortalSlug.CALCOM]
    assert calcom.slug is PortalSlug.CALCOM
    assert calcom.display_name == "Cal.com"
    assert calcom.is_connectable_platform is True
    assert calcom.is_listing_portal is False
    assert calcom.is_externally_publishable is False
    assert calcom.user_id_key is None
    assert "calcom" in P.KNOWN_PLATFORM_SLUGS
    assert "calcom" not in P.LISTING_PORTAL_SLUGS
    assert "calcom" not in P.EXTERNALLY_PUBLISHABLE_SLUGS


def test_every_slug_round_trips_through_the_registry() -> None:
    """The serialization contract every consumer relies on, asserted for the whole
    registry rather than one slug: a slug survives the trip to its stored string form
    and back, and `get_portal_identity` accepts either end of that trip.

    `platform_name` is a plain VARCHAR — the value written to the database is
    `slug.value` and what comes back is a bare `str`, so a member that does not
    reconstruct from its own value would break silently at the read, not the write.
    """
    for slug in PortalSlug:
        stored = slug.value
        assert isinstance(stored, str)
        assert PortalSlug(stored) is slug
        assert f"{slug}" == stored
        assert P.get_portal_identity(stored) is P.get_portal_identity(slug)
        assert P.get_portal_identity(stored).slug is slug


def test_user_id_keys_match_portal_info_contract() -> None:
    assert P.PORTAL_USER_ID_KEYS == {
        "propertyfinder": "public_profile_id",
        "bayut": "user_id",
        "dubizzle": "user_id",
    }
    assert "website" not in P.PORTAL_USER_ID_KEYS
    assert "gemini" not in P.PORTAL_USER_ID_KEYS


def test_dubizzle_routes_under_bayut_provider() -> None:
    assert P.PORTAL_REGISTRY[PortalSlug.DUBIZZLE].provider_key == "bayut"
    assert P.PORTAL_PROVIDER_KEYS["dubizzle"] == "bayut"
    assert P.PORTAL_PROVIDER_KEYS["propertyfinder"] == "propertyfinder"


def test_get_portal_identity_accepts_str_and_enum() -> None:
    assert P.get_portal_identity("bayut") is P.PORTAL_REGISTRY[PortalSlug.BAYUT]
    assert P.get_portal_identity(PortalSlug.BAYUT).display_name == "Bayut"


def test_identity_is_immutable() -> None:
    identity = P.PORTAL_REGISTRY[PortalSlug.PROPERTYFINDER]
    try:
        identity.display_name = "x"  # type: ignore[misc]
    except (AttributeError, TypeError):
        return
    raise AssertionError("PortalIdentity must be frozen")
