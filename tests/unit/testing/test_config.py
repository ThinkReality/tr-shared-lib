"""Opt-in gate and the fingerprint that keeps a warm container honest."""

from __future__ import annotations

from pathlib import Path

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

    def test_table_without_service_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.tr_testing]\nother = 1\n")
        assert find_config(tmp_path) is None

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

    def test_defaults_cover_the_non_trusted_extensions(self, tmp_path: Path) -> None:
        config = find_config(_service(tmp_path))
        assert config is not None
        # All three need a superuser to create; btree_gin was missing from the
        # plan's list and is required by tr-content-platform.
        assert set(config.extensions) == {"pgcrypto", "pg_trgm", "btree_gin"}


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

    def test_key_is_short_enough_for_identifiers(self, tmp_path: Path) -> None:
        config = find_config(_service(tmp_path))
        assert config is not None
        assert len(config.key) == 12
