"""The plugin is inert until a service opts in, and it acts early enough to matter.

Both properties are only observable from a real pytest process, so these tests
drive one. Asserting on imported functions would prove nothing: the entry point,
the hook ordering and the environment mutation are all pytest-runtime behaviour.

Why inertness is load-bearing: the plugin ships as a ``pytest11`` entry point, so
it activates in every venv the moment ``scripts/upgrade-shared-libs.sh`` bumps the
library across all eight services. If it rewrote ``DATABASE_URL`` on install, the
fleet would break before any service had adopted.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_OPT_IN = """
[tool.tr_testing]
service = "tr-demo"
migrate_command = ["true"]
migration_globs = ["migrations/*.py"]
"""

# Records what the environment looked like when the conftest was imported — the
# moment a real service builds its engine from an lru_cached get_settings().
_CONFTEST = """
import json, os, pathlib
pathlib.Path("env_at_conftest_import.json").write_text(json.dumps({
    "DATABASE_URL": os.environ.get("DATABASE_URL"),
    "REDIS_URL": os.environ.get("REDIS_URL"),
    "ENVIRONMENT": os.environ.get("ENVIRONMENT"),
}))
"""

_TEST = """
def test_placeholder():
    assert True
"""


def _project(tmp_path: Path, *, opted_in: bool) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\n' + (_OPT_IN if opted_in else "")
    )
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text(textwrap.dedent(_CONFTEST))
    (tests / "test_demo.py").write_text(textwrap.dedent(_TEST))
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001.py").write_text("revision = '1'\n")
    return tmp_path


def _run_pytest(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/", "-q", "-p", "no:cacheprovider", *args],
        cwd=project,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(project)},
    )


def _recorded(project: Path) -> dict[str, str | None]:
    import json

    return json.loads((project / "env_at_conftest_import.json").read_text())


class TestInertWithoutOptIn:
    def test_does_not_touch_the_environment(self, tmp_path: Path) -> None:
        project = _project(tmp_path, opted_in=False)
        result = _run_pytest(project)
        assert result.returncode == 0, result.stdout + result.stderr

        env = _recorded(project)
        assert env["DATABASE_URL"] is None
        assert env["REDIS_URL"] is None
        assert env["ENVIRONMENT"] is None

    def test_does_not_add_lane_markers(self, tmp_path: Path) -> None:
        """Marking another service's items would change its `-m` selections.

        Contrast with TestActiveAfterOptIn.test_lane_marker_is_derived_from_the_path:
        the identical command selects the test there and deselects it here.
        """
        project = _project(tmp_path, opted_in=False)
        result = _run_pytest(project, "-m", "unit")
        assert "1 deselected" in result.stdout


class TestActiveAfterOptIn:
    def test_env_is_set_before_the_conftest_imports(self, tmp_path: Path) -> None:
        """The whole reason the plugin uses pytest_load_initial_conftests.

        Services build their engine at import time from an lru_cached
        get_settings(), inside tests/conftest.py. pytest_configure runs after
        that, and a pytest_plugins-declared plugin imports after it too.
        """
        project = _project(tmp_path, opted_in=True)
        result = _run_pytest(project)
        assert result.returncode == 0, result.stdout + result.stderr

        env = _recorded(project)
        assert env["ENVIRONMENT"] == "test"
        assert env["DATABASE_URL"] is not None

    def test_unit_lane_gets_the_poison_dsn_and_never_calls_docker(
        self, tmp_path: Path
    ) -> None:
        """A unit run must not provision — and must fail loudly if it connects."""
        from tr_shared.testing.lanes import POISON_DATABASE_URL, POISON_REDIS_URL

        project = _project(tmp_path, opted_in=True)
        result = _run_pytest(project)
        assert result.returncode == 0, result.stdout + result.stderr

        env = _recorded(project)
        assert env["DATABASE_URL"] == POISON_DATABASE_URL
        assert env["REDIS_URL"] == POISON_REDIS_URL

    def test_lane_marker_is_derived_from_the_path(self, tmp_path: Path) -> None:
        project = _project(tmp_path, opted_in=True)
        selected = _run_pytest(project, "-m", "unit")
        assert selected.returncode == 0, selected.stdout + selected.stderr
        assert "1 passed" in selected.stdout

        deselected = _run_pytest(project, "-m", "integration")
        assert "1 deselected" in deselected.stdout


class TestRemoteDsnIsRefused:
    def test_non_local_test_database_url_aborts(self, tmp_path: Path) -> None:
        """G1. Hard failure, never a skip — fixtures TRUNCATE and DROP DATABASE."""
        project = _project(tmp_path, opted_in=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/",  # unclassified path -> integration lane -> DSN is checked
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=project,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(project),
                "TEST_DATABASE_URL": (
                    "postgresql+asyncpg://postgres:pw"
                    "@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
                ),
            },
        )
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "non-local host" in combined
        assert "supabase.com" in combined

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
    def test_local_test_database_url_is_accepted(self, tmp_path: Path, host: str) -> None:
        project = _project(tmp_path, opted_in=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"],
            cwd=project,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(project),
                "TEST_DATABASE_URL": f"postgresql+asyncpg://u:p@{host}:5432/db",
            },
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _recorded(project)["DATABASE_URL"] == (
            f"postgresql+asyncpg://u:p@{host}:5432/db"
        )
