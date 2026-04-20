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
