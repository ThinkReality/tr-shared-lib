"""Constants are contract: cross-service alignment must not drift."""

from tr_shared.integrations import constants as K


def test_pf_platform_name_exact_string() -> None:
    """Admin panel writes this exact string — any drift breaks lookups."""
    assert K.PF_PLATFORM_NAME == "PropertyFinder API"


def test_pf_auth_url_matches_token_manager_reference() -> None:
    assert K.PF_AUTH_URL == "https://auth.propertyfinder.com/auth/oauth/v1/token"


def test_all_pf_webhook_events_has_13() -> None:
    """PF API publishes exactly 13 event types — do not add/remove here
    without a matching admin-panel migration."""
    assert len(K.ALL_PF_WEBHOOK_EVENTS) == 13
    assert len(set(K.ALL_PF_WEBHOOK_EVENTS)) == 13  # unique


def test_known_pf_event_prefixes_cover_all_events() -> None:
    """Every ALL_PF_WEBHOOK_EVENTS entry must start with one of the known prefixes."""
    for event in K.ALL_PF_WEBHOOK_EVENTS:
        assert any(event.startswith(p) for p in K.KNOWN_PF_EVENT_PREFIXES), (
            f"event {event!r} has no matching prefix in KNOWN_PF_EVENT_PREFIXES"
        )


def test_pf_platform_name_is_in_known_platform_names() -> None:
    assert K.PF_PLATFORM_NAME in K.KNOWN_PLATFORM_NAMES


def test_frozenset_immutability() -> None:
    """Downstream code must not be able to mutate these constants."""
    assert isinstance(K.KNOWN_PLATFORM_NAMES, frozenset)
    assert isinstance(K.KNOWN_PF_EVENT_PREFIXES, frozenset)
    assert isinstance(K.ALL_PF_WEBHOOK_EVENTS, tuple)
    assert isinstance(K.PUBLIC_CONFIG_KEYS, frozenset)


# ---------------------------------------------------------------------------
# GEMINI_PLATFORM_NAME + KNOWN_PLATFORM_NAMES drift guard
# ---------------------------------------------------------------------------


def test_gemini_platform_name_exact_string() -> None:
    assert K.GEMINI_PLATFORM_NAME == "Google Gemini AI"


def test_known_platform_names_includes_gemini() -> None:
    assert K.GEMINI_PLATFORM_NAME in K.KNOWN_PLATFORM_NAMES


def test_known_platform_names_has_exactly_pf_and_gemini() -> None:
    assert K.KNOWN_PLATFORM_NAMES == frozenset(
        {K.PF_PLATFORM_NAME, K.GEMINI_PLATFORM_NAME},
    )


# ---------------------------------------------------------------------------
# PUBLIC_CONFIG_KEYS allowlist + sanitize_public_config
# ---------------------------------------------------------------------------


def test_public_config_keys_contains_expected_entries() -> None:
    expected = {
        "webhook_token",
        "environment",
        "region",
        "auto_publish",
        "registration_type",
        "connected_at",
        "subscription_count",
    }
    assert K.PUBLIC_CONFIG_KEYS == frozenset(expected)


def test_sanitize_public_config_drops_unknown_keys() -> None:
    dirty = {
        "webhook_token": "wh_123",
        "api_key": "SECRET",
        "api_secret": "SECRET",
        "oauth_refresh_token": "SECRET",
        "environment": "staging",
    }
    clean = K.sanitize_public_config(dirty)
    assert clean == {"webhook_token": "wh_123", "environment": "staging"}


def test_sanitize_public_config_empty_input() -> None:
    assert K.sanitize_public_config(None) == {}
    assert K.sanitize_public_config({}) == {}


def test_sanitize_public_config_returns_new_dict() -> None:
    src = {"webhook_token": "x"}
    out = K.sanitize_public_config(src)
    out["webhook_token"] = "mutated"
    assert src["webhook_token"] == "x"
