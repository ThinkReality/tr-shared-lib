"""The .env.example contract guard, and its shell-consumed exemption.

Some env keys are consumed by shell, not Python — tr-api-gateway's
RUN_MIGRATIONS_ON_STARTUP is read by deploy.sh. Those must not be reported.
The exemption is derived by GREPPING compose/Dockerfile/*.sh for the key name,
never from a prose allowlist: a written exemption cannot be checked, and one
that names instances instead of the rule rots the moment the repo changes.
"""

import tempfile
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from tr_shared.testing.env_contract import assert_env_example_is_declared


class _Svc(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    SERVICE_NAME: str = "x"


class _CaseSensitiveExample(BaseSettings):
    """A distinctively-named field so this test can't accidentally be
    satisfied by some other reachable BaseSettings subclass in the process."""

    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, extra="ignore")

    ENV_CONTRACT_CASE_PIN: str = "unset"


def _repo(example: str, *, deploy_sh: str = "") -> Path:
    root = Path(tempfile.mkdtemp())
    (root / ".env.example").write_text(example, encoding="utf-8")
    if deploy_sh:
        (root / "deploy.sh").write_text(deploy_sh, encoding="utf-8")
    return root


def test_declared_keys_pass() -> None:
    assert_env_example_is_declared(_repo("SERVICE_NAME=x\n"), extra_classes=(_Svc,))


def test_an_undeclared_key_fails_and_names_itself() -> None:
    root = _repo("SERVICE_NAME=x\nSTALE_RENAMED_KEY=1\n")

    with pytest.raises(AssertionError, match="STALE_RENAMED_KEY"):
        assert_env_example_is_declared(root, extra_classes=(_Svc,))


def test_a_shell_consumed_key_is_exempt() -> None:
    root = _repo(
        "SERVICE_NAME=x\nRUN_MIGRATIONS_ON_STARTUP=true\n",
        deploy_sh='if [ "$RUN_MIGRATIONS_ON_STARTUP" = "true" ]; then alembic upgrade head; fi\n',
    )

    assert_env_example_is_declared(root, extra_classes=(_Svc,))


def test_a_substring_match_does_not_grant_exemption() -> None:
    """RUN_MIGRATIONS must not be exempted by a file mentioning RUN_MIGRATIONS_ON_STARTUP."""
    root = _repo(
        "SERVICE_NAME=x\nRUN_MIGRATIONS=true\n",
        deploy_sh="echo $RUN_MIGRATIONS_ON_STARTUP\n",
    )

    with pytest.raises(AssertionError, match="RUN_MIGRATIONS"):
        assert_env_example_is_declared(root, extra_classes=(_Svc,))


def test_a_case_sensitive_classs_wrong_case_key_still_fails_through_this_entry_point() -> None:
    """Pins the Finding-3 fix through this entry point too: a lowercase
    .env.example key must not be accepted just because its upper-cased form
    coincidentally matches a case-sensitive class's declared name — this
    guard must delegate to unclaimed_env_keys, not re-implement the
    comparison without case handling."""
    root = _repo("SERVICE_NAME=x\nenv_contract_case_pin=1\n")

    with pytest.raises(AssertionError, match="env_contract_case_pin"):
        assert_env_example_is_declared(root, extra_classes=(_Svc, _CaseSensitiveExample))
