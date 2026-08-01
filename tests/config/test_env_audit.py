"""An env key that no settings class claims must be reported.

Settings classes are extra="ignore", so a renamed or typo'd key is discarded in
silence. tr-crm-core kept PROPERTYFINDER_API_BASE_URL in .env after the field
was renamed to PF_API_BASE_URL; dev resolved to the production default for days
and every test passed, because a test cannot see a .env.

The collector must union EVERY reachable BaseSettings subclass, with each
class's env_prefix applied. One .env feeds many classes — AuthLibSettings
(AUTH_LIB_), WAM's LLMConfig (LLM_), realty-hub's module settings. Comparing
against the primary Settings alone reports live keys as orphans.
"""

import os
import sys
from pathlib import Path

import pytest
import structlog.testing
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from tr_shared.config.env_audit import (
    _declared_env_keys,
    log_unclaimed_env_keys,
    parse_env_keys,
    unclaimed_env_keys,
)


class _Primary(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    SERVICE_NAME: str = "x"
    PF_API_BASE_URL: str = "https://example.test"


class _Prefixed(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, env_prefix="AUTH_LIB_", extra="ignore")

    DEV_MODE_BYPASS: bool = False


class _AliasedPrefixed(BaseSettings):
    """Shape of shared-auth-lib's AuthLibSettings.ENVIRONMENT: a prefixed class
    with one field carrying an explicit bare-string alias."""

    model_config = SettingsConfigDict(env_file=None, env_prefix="AUTH_LIB_", extra="ignore")

    environment: str = Field(default="development", validation_alias="ENVIRONMENT")


class _AliasedPrefixedTargetAll(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None, env_prefix="AUTH_LIB_", env_prefix_target="all", extra="ignore"
    )

    environment: str = Field(default="development", validation_alias="ENVIRONMENT")


class _AliasChoicesPrefixed(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, env_prefix="AUTH_LIB_", extra="ignore")

    token: str = Field(default="unset", validation_alias=AliasChoices("SERVICE_TOKEN", "TOKEN"))


class _CaseSensitivePrefixed(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None, env_prefix="AUTH_LIB_", case_sensitive=True, extra="ignore"
    )

    Mixed_Case: str = "unset"


class _CaseSensitiveScreamingSnake(BaseSettings):
    """Mirrors tr_shared.config.base.BaseServiceSettings — case_sensitive=True
    with an already-SCREAMING_SNAKE_CASE field, inherited by every service.
    This is the exact shape that let a blanket ``key.upper() in declared``
    check mask a real case mismatch: the declared name and the upper-cased
    candidate key look identical as bare strings even though this class would
    never actually bind a lowercase env var."""

    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, extra="ignore")

    SERVICE_NAME: str = "default-unbound"


class _MixedRunCaseSensitive(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, extra="ignore")

    ONLY_EXACT: str = "unset"


class _MixedRunCaseInsensitive(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    ONLY_LOOSE: str = "unset"


@pytest.fixture
def env_file(tmp_path: Path):
    """Writes a .env into pytest's tmp_path and hands back its path."""

    def _write(body: str) -> Path:
        path = tmp_path / ".env"
        path.write_text(body, encoding="utf-8")
        return path

    return _write


def test_parse_env_keys_reads_names_only(env_file) -> None:
    path = env_file(
        "\n".join(
            [
                "# a comment",
                "",
                "SERVICE_NAME=crm-core",
                "  SPACED_KEY = value with = signs ",
                "export EXPORTED_KEY=1",
                "EMPTY_KEY=",
            ]
        )
    )

    assert parse_env_keys(path) == {
        "SERVICE_NAME",
        "SPACED_KEY",
        "EXPORTED_KEY",
        "EMPTY_KEY",
    }


def test_empty_valued_keys_are_still_keys(env_file) -> None:
    """pydantic's own forbid skips these. A stale key with no value is still stale."""
    assert "EMPTY_KEY" in parse_env_keys(env_file("EMPTY_KEY=\n"))


def test_declared_env_keys_applies_env_prefix() -> None:
    declared = _declared_env_keys(_Primary, _Prefixed)

    assert "SERVICE_NAME" in declared
    assert "PF_API_BASE_URL" in declared
    assert "AUTH_LIB_DEV_MODE_BYPASS" in declared
    assert "DEV_MODE_BYPASS" not in declared


def test_a_renamed_key_is_reported_as_unclaimed(env_file) -> None:
    path = env_file("PROPERTYFINDER_API_BASE_URL=https://sandbox.example\nSERVICE_NAME=crm-core\n")

    assert unclaimed_env_keys(path, classes=(_Primary, _Prefixed)) == [
        "PROPERTYFINDER_API_BASE_URL"
    ]


def test_a_key_owned_by_a_prefixed_class_is_not_reported(env_file) -> None:
    """The false-positive that would push someone into re-declaring AUTH_LIB_*."""
    path = env_file("AUTH_LIB_DEV_MODE_BYPASS=true\nSERVICE_NAME=crm-core\n")

    assert unclaimed_env_keys(path, classes=(_Primary, _Prefixed)) == []


def test_missing_env_file_reports_nothing() -> None:
    assert unclaimed_env_keys(Path("/nonexistent/.env"), classes=(_Primary,)) == []


# --- CRITICAL 1: env_prefix must not be applied to an explicit alias -------
# pydantic-settings' default env_prefix_target is "variable": the prefix
# applies only to the un-aliased field-name path. A field with an explicit
# alias is populated by the BARE alias unless the class opts into
# env_prefix_target="alias"/"all". Verified against pydantic-settings 2.13.1
# by reading PydanticBaseEnvSettingsSource._extract_field_info in
# pydantic_settings/sources/base.py and confirming empirically.


def test_aliased_field_on_prefixed_class_yields_bare_alias_only() -> None:
    """shared-auth-lib's AuthLibSettings.ENVIRONMENT shape: AUTH_LIB_ prefix,
    field aliased to the bare "ENVIRONMENT" var. Every service's .env sets
    ENVIRONMENT — it must not be reported as an orphan."""
    declared = _declared_env_keys(_AliasedPrefixed)

    assert "ENVIRONMENT" in declared
    assert "AUTH_LIB_ENVIRONMENT" not in declared


def test_aliased_field_with_env_prefix_target_all_yields_prefixed_alias() -> None:
    declared = _declared_env_keys(_AliasedPrefixedTargetAll)

    assert "AUTH_LIB_ENVIRONMENT" in declared
    assert "ENVIRONMENT" not in declared


def test_alias_choices_on_prefixed_class_yields_bare_choices() -> None:
    declared = _declared_env_keys(_AliasChoicesPrefixed)

    assert "SERVICE_TOKEN" in declared
    assert "TOKEN" in declared
    assert "AUTH_LIB_SERVICE_TOKEN" not in declared
    assert "AUTH_LIB_TOKEN" not in declared


def test_environment_alias_is_not_reported_unclaimed(env_file) -> None:
    """The exact false positive that shipped: 8 services' .env sets
    ENVIRONMENT, and it must not be flagged as unclaimed by AuthLibSettings'
    AUTH_LIB_ prefix."""
    path = env_file("ENVIRONMENT=development\n")

    assert unclaimed_env_keys(path, classes=(_AliasedPrefixed,)) == []


# --- CRITICAL 2: a missing/unreadable/non-UTF-8 .env must never raise ------


def test_parse_env_keys_returns_empty_for_unreadable_file(tmp_path: Path) -> None:
    if sys.platform == "win32" or os.geteuid() == 0:
        pytest.skip("permission bits are not enforced for root or on Windows")

    path = tmp_path / ".env"
    path.write_text("SERVICE_NAME=crm-core\n", encoding="utf-8")
    path.chmod(0o000)
    try:
        assert parse_env_keys(path) == set()
    finally:
        path.chmod(0o644)


def test_parse_env_keys_returns_empty_for_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"SERVICE_NAME=\xff\xfe invalid utf-8\n")

    assert parse_env_keys(path) == set()


def test_log_unclaimed_env_keys_never_raises_for_missing_file() -> None:
    assert log_unclaimed_env_keys(Path("/nonexistent/.env")) == []


def test_log_unclaimed_env_keys_is_silent_for_missing_file() -> None:
    """A missing .env is normal in staging/prod (config comes from OS env
    vars) — it must not warn."""
    with structlog.testing.capture_logs() as cap:
        log_unclaimed_env_keys(Path("/nonexistent/.env"))

    assert cap == []


def test_log_unclaimed_env_keys_never_raises_for_unreadable_file(tmp_path: Path) -> None:
    if sys.platform == "win32" or os.geteuid() == 0:
        pytest.skip("permission bits are not enforced for root or on Windows")

    path = tmp_path / ".env"
    path.write_text("SERVICE_NAME=crm-core\n", encoding="utf-8")
    path.chmod(0o000)
    try:
        with structlog.testing.capture_logs() as cap:
            assert log_unclaimed_env_keys(path) == []
    finally:
        path.chmod(0o644)

    assert any(entry["event"] == "env_file_unreadable" for entry in cap), (
        "an unreadable (but present) .env should warn, not fail silently"
    )


def test_log_unclaimed_env_keys_never_raises_for_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"SERVICE_NAME=\xff\xfe invalid utf-8\n")

    with structlog.testing.capture_logs() as cap:
        assert log_unclaimed_env_keys(path) == []

    assert any(entry["event"] == "env_file_unreadable" for entry in cap)


# --- CRITICAL 3: case-sensitive classes must not be merged with the
# case-insensitive comparison — doing so produces a FALSE NEGATIVE, not a
# false positive. A blanket `key.upper() in declared` over one merged set lets
# a case-insensitive-only match stand in for a case-sensitive class's
# exact-match requirement whenever the case-sensitive class's field name is
# already SCREAMING_SNAKE_CASE — which BaseServiceSettings (case_sensitive=True,
# inherited by every service) always is. Verified directly: pydantic-settings
# does NOT bind service_name to a case_sensitive=True SERVICE_NAME field, so
# the audit reporting it as claimed was worse than the round-1 false positive
# — it under-reports a genuinely dead key.


def test_lowercase_env_key_is_not_reported_unclaimed_for_case_insensitive_class(
    env_file,
) -> None:
    """pydantic-settings' default case_sensitive=False binds a lowercase .env
    key to an upper-cased field name; the audit must agree."""
    path = env_file("service_name=crm-core\n")

    assert unclaimed_env_keys(path, classes=(_Primary,)) == []


def test_mismatched_case_key_is_reported_unclaimed_for_case_sensitive_class(
    env_file,
) -> None:
    """case_sensitive=True means pydantic-settings itself would not bind this
    key either — the audit must agree and report it."""
    path = env_file("AUTH_LIB_MIXED_CASE=x\n")

    assert unclaimed_env_keys(path, classes=(_CaseSensitivePrefixed,)) == ["AUTH_LIB_MIXED_CASE"]


def test_case_sensitive_class_with_lowercase_key_is_reported_unclaimed(env_file) -> None:
    """The exact false negative reported in review: a case-sensitive class
    with an already-uppercase field name, and a lowercase .env key that
    pydantic-settings would never bind to it."""
    path = env_file("service_name=crm-core\n")

    assert unclaimed_env_keys(path, classes=(_CaseSensitiveScreamingSnake,)) == ["service_name"]


def test_case_sensitive_class_with_exact_case_key_is_not_reported_unclaimed(
    env_file,
) -> None:
    path = env_file("SERVICE_NAME=crm-core\n")

    assert unclaimed_env_keys(path, classes=(_CaseSensitiveScreamingSnake,)) == []


def test_mixed_case_sensitive_and_insensitive_owners_each_claim_their_own_key(
    env_file,
) -> None:
    """A case-sensitive and a case-insensitive class present together: each
    key is bound by exactly one of them, and both must be recognized."""
    path = env_file("ONLY_EXACT=x\nonly_loose=y\n")

    assert (
        unclaimed_env_keys(path, classes=(_MixedRunCaseSensitive, _MixedRunCaseInsensitive)) == []
    )


def test_mixed_run_case_sensitive_owner_requirement_is_not_loosened_by_a_co_present_insensitive_owner(
    env_file,
) -> None:
    """The presence of a case-insensitive owner in the same call must not let
    a case-sensitive owner's exact-match requirement be satisfied by a
    wrong-case key."""
    path = env_file("only_exact=x\n")

    assert unclaimed_env_keys(path, classes=(_MixedRunCaseSensitive, _MixedRunCaseInsensitive)) == [
        "only_exact"
    ]


def test_exact_case_key_is_not_reported_unclaimed_for_case_sensitive_class(
    env_file,
) -> None:
    path = env_file("AUTH_LIB_Mixed_Case=x\n")

    assert unclaimed_env_keys(path, classes=(_CaseSensitivePrefixed,)) == []


class _SettingsDefinedInATestModule(BaseSettings):
    """A fixture class, not service config. Its module is part of the test tree,
    which is exactly what makes it ineligible to own a key."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    A_KEY_NO_SERVICE_DECLARES: str = "x"


def test_a_test_defined_settings_class_never_claims_a_key(tmp_path: Path) -> None:
    """M4: auto-discovery must not treat test fixture classes as config owners.

    Without this, a fixture that happens to declare a key turns a real orphan
    into a clean result — a false negative in the guard whose entire job is finding
    keys nothing owns.
    """
    env = tmp_path / ".env.example"
    env.write_text("A_KEY_NO_SERVICE_DECLARES=1\n", encoding="utf-8")

    assert _SettingsDefinedInATestModule.model_fields  # the class is live and reachable
    assert unclaimed_env_keys(env) == ["A_KEY_NO_SERVICE_DECLARES"]


def test_explicitly_passed_classes_are_still_honoured(tmp_path: Path) -> None:
    """The exclusion applies to inference, never to what a caller states outright.

    `classes=` is the caller's intent. The .env.example assertion helper's
    `extra_classes=` rides on it, and the lib's own contract tests pass fixture
    classes there deliberately.
    """
    env = tmp_path / ".env.example"
    env.write_text("A_KEY_NO_SERVICE_DECLARES=1\n", encoding="utf-8")

    assert unclaimed_env_keys(env, classes=(_SettingsDefinedInATestModule,)) == []
