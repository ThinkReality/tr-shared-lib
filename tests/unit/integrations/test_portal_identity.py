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
        {"propertyfinder", "bayut", "dubizzle", "gemini"},
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
