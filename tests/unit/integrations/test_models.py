"""Tests for IntegrationConfig data model."""

import pytest
from pydantic import ValidationError

from tr_shared.integrations import IntegrationConfig


def _base_fields() -> dict:
    return {
        "platform_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "platform_name": "PropertyFinder API",
        "platform_type": "portal",
        "config": {},
        "is_enabled": True,
    }


def test_round_trip() -> None:
    cfg = IntegrationConfig(**_base_fields())
    assert cfg.platform_name == "PropertyFinder API"
    assert cfg.is_enabled is True


def test_frozen_cannot_be_mutated() -> None:
    cfg = IntegrationConfig(**_base_fields())
    with pytest.raises(ValidationError):
        cfg.is_enabled = False  # type: ignore[misc]


def test_get_secret_returns_value_when_present() -> None:
    cfg = IntegrationConfig(**{**_base_fields(), "config": {"api_key": "k123"}})
    assert cfg.get_secret("api_key") == "k123"


def test_get_secret_returns_default_when_absent() -> None:
    cfg = IntegrationConfig(**_base_fields())
    assert cfg.get_secret("api_key") == ""
    assert cfg.get_secret("api_key", default="fallback") == "fallback"


def test_get_secret_returns_default_when_none_value() -> None:
    """None-valued config entries must not leak to callers as 'None'."""
    cfg = IntegrationConfig(**{**_base_fields(), "config": {"api_key": None}})
    assert cfg.get_secret("api_key", default="x") == "x"


def test_get_secret_coerces_non_str_to_str() -> None:
    cfg = IntegrationConfig(**{**_base_fields(), "config": {"retry_count": 5}})
    assert cfg.get_secret("retry_count") == "5"
