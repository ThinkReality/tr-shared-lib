"""Opt-in gate and the fingerprint that keeps a warm container honest."""

from __future__ import annotations

from pathlib import Path

import pytest

from tr_shared.testing import config as config_module
from tr_shared.testing.config import find_config

_OPTED_IN = """
[project]
name = "svc"

[tool.tr_testing]
service = "tr-demo"
migrate_command = ["migrate", "upgrade", "head"]
migration_globs = ["app/alembic/versions/*.py"]
"""


def _service(tmp_path: Path, pyproject: str = _OPTED_IN) -> Path:
    (tmp_path / "pyproject.toml").write_text(pyproject)
    versions = tmp_path / "app" / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_baseline.py").write_text("revision = '0001'\n")
    return tmp_path


class TestOptIn:
    def test_absent_table_returns_none(self, tmp_path: Path) -> None:
        """The bump lands in eight services at once; silence is the requirement."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "svc"\n')
        assert find_config(tmp_path) is None

    def test_no_pyproject_at_all_returns_none(self, tmp_path: Path) -> None:
        assert find_config(tmp_path) is None

    def test_malformed_pyproject_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("this is not = valid toml [[[")
        assert find_config(tmp_path) is None

    def test_table_without_service_is_a_usage_error(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[tool.tr_testing]\ndatabase_name = "x"\n')
        with pytest.raises(pytest.UsageError, match="service"):
            find_config(tmp_path)

    def test_opted_in_is_found(self, tmp_path: Path) -> None:
        config = find_config(_service(tmp_path))
        assert config is not None
        assert config.service == "tr-demo"
        assert config.migrate_command == ("migrate", "upgrade", "head")

    def test_found_from_a_subdirectory(self, tmp_path: Path) -> None:
        root = _service(tmp_path)
        nested = root / "tests" / "unit"
        nested.mkdir(parents=True)
        config = find_config(nested)
        assert config is not None and config.root == root


class TestFingerprint:
    def test_stable_across_calls(self, tmp_path: Path) -> None:
        config = find_config(_service(tmp_path))
        assert config is not None
        assert config.fingerprint() == config.fingerprint()

    def test_changes_when_a_migration_changes(self, tmp_path: Path) -> None:
        root = _service(tmp_path)
        before = find_config(root)
        assert before is not None
        first = before.fingerprint()

        (root / "app" / "alembic" / "versions" / "0001_baseline.py").write_text(
            "revision = '0001'\n# edited in place while re-baselining\n"
        )
        after = find_config(root)
        assert after is not None
        # Content, not filenames: editing a migration in place must invalidate
        # the template, or the next run clones a stale schema.
        assert after.fingerprint() != first

    def test_changes_when_a_migration_is_added(self, tmp_path: Path) -> None:
        root = _service(tmp_path)
        before = find_config(root)
        assert before is not None
        first = before.fingerprint()

        (root / "app" / "alembic" / "versions" / "0002_next.py").write_text("x = 1\n")
        after = find_config(root)
        assert after is not None
        assert after.fingerprint() != first

    def test_changes_when_the_image_changes(self, tmp_path: Path) -> None:
        root = _service(tmp_path)
        before = find_config(root)
        assert before is not None
        first = before.fingerprint()

        (root / "pyproject.toml").write_text(
            _OPTED_IN + '\npostgres_image = "postgres:17-alpine"\n'
        )
        after = find_config(root)
        assert after is not None
        assert after.fingerprint() != first

    def test_changes_when_the_database_layout_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _service(tmp_path)
        before = find_config(root)
        assert before is not None
        first = before.fingerprint()

        monkeypatch.setattr(
            config_module, "DATABASE_LAYOUT", (*config_module.DATABASE_LAYOUT, "SELECT 1")
        )
        after = find_config(root)
        assert after is not None
        assert after.fingerprint() != first

    def test_key_is_short_enough_for_identifiers(self, tmp_path: Path) -> None:
        config = find_config(_service(tmp_path))
        assert config is not None
        assert len(config.key) == 12


class TestEnvTable:
    def test_table_values_are_parsed_in_order(self, tmp_path: Path) -> None:
        root = _service(tmp_path, _OPTED_IN + '\n[tool.tr_testing.env]\nB_KEY = "2"\nA_KEY = "1"\n')
        config = find_config(root)
        assert config is not None
        assert config.env == (("B_KEY", "2"), ("A_KEY", "1"))

    def test_no_table_is_an_empty_env(self, tmp_path: Path) -> None:
        config = find_config(_service(tmp_path))
        assert config is not None
        assert config.env == ()

    def test_a_non_table_env_is_a_usage_error(self, tmp_path: Path) -> None:
        root = _service(tmp_path, _OPTED_IN + 'env = "A=1"\n')
        with pytest.raises(pytest.UsageError, match="env"):
            find_config(root)

    def test_a_non_string_value_is_a_usage_error(self, tmp_path: Path) -> None:
        root = _service(tmp_path, _OPTED_IN + "\n[tool.tr_testing.env]\nPORT = 8000\n")
        with pytest.raises(pytest.UsageError, match="PORT"):
            find_config(root)

    @pytest.mark.parametrize(
        "key", ["DATABASE_URL", "database_url", "ENVIRONMENT", "TR_TESTING_RUN_ID"]
    )
    def test_an_owned_key_is_a_usage_error(self, tmp_path: Path, key: str) -> None:
        root = _service(tmp_path, _OPTED_IN + f'\n[tool.tr_testing.env]\n{key} = "x"\n')
        with pytest.raises(pytest.UsageError, match=key):
            find_config(root)

    def test_the_fingerprint_ignores_the_table(self, tmp_path: Path) -> None:
        root = _service(tmp_path)
        without = find_config(root)
        assert without is not None
        (root / "pyproject.toml").write_text(_OPTED_IN + '\n[tool.tr_testing.env]\nA_KEY = "1"\n')
        with_table = find_config(root)
        assert with_table is not None
        assert with_table.env == (("A_KEY", "1"),)
        assert with_table.fingerprint() == without.fingerprint()


class TestStrictTable:
    def test_an_unknown_key_is_a_usage_error(self, tmp_path: Path) -> None:
        root = _service(tmp_path, _OPTED_IN + 'envs = "x"\n')
        with pytest.raises(pytest.UsageError, match="envs"):
            find_config(root)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("service", '""'),
            ("service", "1"),
            ("migrate_command", '"alembic upgrade head"'),
            ("migrate_command", "[1, 2]"),
            ("migrate_command", "[]"),
            ("migration_globs", '"*.py"'),
            ("postgres_image", "17"),
            ("postgres_image", '""'),
            ("redis_image", "[]"),
            ("database_name", "true"),
        ],
    )
    def test_a_wrong_typed_known_key_is_a_usage_error(
        self, tmp_path: Path, key: str, value: str
    ) -> None:
        lines = [line for line in _OPTED_IN.splitlines() if not line.startswith(f"{key} =")]
        root = _service(tmp_path, "\n".join([*lines, f"{key} = {value}", ""]))
        with pytest.raises(pytest.UsageError, match=key):
            find_config(root)


class TestEnvConstants:
    @pytest.mark.parametrize("key", ["UV_ENV_FILE", "GITHUB_PERSONAL_ACCESS_TOKEN"])
    def test_a_leaky_variable_does_not_pass_the_scrub(self, key: str) -> None:
        assert not config_module.passes_scrub(key)

    @pytest.mark.parametrize(
        "key",
        ["database_url", "DATABASE_URL", "SLACK_ERROR_WEBHOOK_URL", "VIRTUAL_ENV", "GITHUB_TOKEN"],
    )
    def test_config_and_secrets_do_not_pass_the_scrub(self, key: str) -> None:
        assert not config_module.passes_scrub(key)

    @pytest.mark.parametrize(
        "key",
        [
            "PATH",
            "HOME",
            "LC_ALL",
            "PYTHONHASHSEED",
            "PYTEST_ADDOPTS",
            "http_proxy",
            "GITHUB_ACTIONS",
            "TR_TESTING_RUN_ID",
        ],
    )
    def test_listed_and_prefixed_names_pass_the_scrub(self, key: str) -> None:
        assert config_module.passes_scrub(key)

    def test_every_passthrough_entry_has_a_reason(self) -> None:
        assert all(reason.strip() for reason in config_module.ENV_PASSTHROUGH.values())

    def test_the_owned_set_is_the_union_of_its_parts(self) -> None:
        assert config_module.PLUGIN_OWNED_ENV == frozenset(
            {*config_module.INFRA_ENV, *config_module.POLICY_ENV, *config_module.CONTROL_ENV}
        )

    def test_policy_gives_the_two_tokens_distinct_values(self) -> None:
        policy = config_module.POLICY_ENV
        assert policy["ENVIRONMENT"] == "test"
        assert policy["AUTH_LIB_SERVICE_TOKEN"] != policy["SERVICE_TOKEN"]
