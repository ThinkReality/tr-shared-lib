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

from tr_shared.testing.env_contract import assert_no_orphan_env_keys


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
    assert_no_orphan_env_keys(_repo("SERVICE_NAME=x\n"), extra_classes=(_Svc,))


def test_an_undeclared_key_fails_and_names_itself() -> None:
    root = _repo("SERVICE_NAME=x\nSTALE_RENAMED_KEY=1\n")

    with pytest.raises(AssertionError, match="STALE_RENAMED_KEY"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_shell_consumed_key_is_exempt() -> None:
    root = _repo(
        "SERVICE_NAME=x\nRUN_MIGRATIONS_ON_STARTUP=true\n",
        deploy_sh='if [ "$RUN_MIGRATIONS_ON_STARTUP" = "true" ]; then alembic upgrade head; fi\n',
    )

    assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_substring_match_does_not_grant_exemption() -> None:
    """RUN_MIGRATIONS must not be exempted by a file mentioning RUN_MIGRATIONS_ON_STARTUP."""
    root = _repo(
        "SERVICE_NAME=x\nRUN_MIGRATIONS=true\n",
        deploy_sh="echo $RUN_MIGRATIONS_ON_STARTUP\n",
    )

    with pytest.raises(AssertionError, match="RUN_MIGRATIONS"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_case_sensitive_classs_wrong_case_key_still_fails_through_this_entry_point() -> None:
    """Pins the Finding-3 fix through this entry point too: a lowercase
    .env.example key must not be accepted just because its upper-cased form
    coincidentally matches a case-sensitive class's declared name — this
    guard must delegate to unclaimed_env_keys, not re-implement the
    comparison without case handling."""
    root = _repo("SERVICE_NAME=x\nenv_contract_case_pin=1\n")

    with pytest.raises(AssertionError, match="env_contract_case_pin"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc, _CaseSensitiveExample))


def test_a_key_read_by_go_source_is_exempt() -> None:
    """M6: WAM's Go bot reads WHATSMEOW_DB_PATH and CREWAI_BASE_URL via os.Getenv.

    Reported as orphans, the guard's own message tells the developer to delete two
    keys the bot needs to boot - the guard causing the outage it exists to prevent.
    Python is not the only runtime in this monorepo, so it cannot be the only
    thing that counts as a consumer.
    """
    root = _repo("WHATSMEOW_DB_PATH=/data/whatsmeow.db\n")
    (root / "go-whatsapp-bot").mkdir()
    (root / "go-whatsapp-bot" / "main.go").write_text(
        'func main() { dbPath := os.Getenv("WHATSMEOW_DB_PATH") }\n', encoding="utf-8"
    )

    assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_key_no_consumer_of_any_language_reads_still_fails() -> None:
    """The widening must not become a blanket pass. A key mentioned nowhere is
    still an orphan even once .go files are scanned."""
    root = _repo("SERVICE_NAME=x\nSTALE_RENAMED_KEY=1\n")
    (root / "go-whatsapp-bot").mkdir()
    (root / "go-whatsapp-bot" / "main.go").write_text(
        'func main() { _ = os.Getenv("SOMETHING_ELSE") }\n', encoding="utf-8"
    )

    with pytest.raises(AssertionError, match="STALE_RENAMED_KEY"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))


def test_a_worktree_copy_of_this_repo_cannot_exempt_a_key() -> None:
    """A worktree holds a copy of this same repo at another revision. Scanning it
    lets a key that only some other branch consumes look claimed here — a false
    negative that depends on what a colleague is mid-way through. iter_shell_files
    has skipped .worktrees for this reason since it was written; this scan must
    skip the same four directories.
    """
    root = _repo("SERVICE_NAME=x\nSTALE_RENAMED_KEY=1\n")
    other_branch = root / ".worktrees" / "some-branch"
    other_branch.mkdir(parents=True)
    (other_branch / "deploy.sh").write_text("echo $STALE_RENAMED_KEY\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="STALE_RENAMED_KEY"):
        assert_no_orphan_env_keys(root, extra_classes=(_Svc,))
