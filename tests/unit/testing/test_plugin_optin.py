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
    "SERVICE_TOKEN": os.environ.get("SERVICE_TOKEN"),
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


def _run_pytest(project: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/", "-q", "-p", "no:cacheprovider", *args],
        cwd=project,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(project), **env},
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
        from tr_shared.testing.config import POLICY_ENV

        project = _project(tmp_path, opted_in=True)
        result = _run_pytest(project, ENVIRONMENT="development", SERVICE_TOKEN="x")
        assert result.returncode == 0, result.stdout + result.stderr

        env = _recorded(project)
        assert env["ENVIRONMENT"] == "test"
        assert env["SERVICE_TOKEN"] == POLICY_ENV["SERVICE_TOKEN"]
        assert env["DATABASE_URL"] is not None

    def test_unit_lane_gets_the_poison_dsn_and_never_calls_docker(self, tmp_path: Path) -> None:
        """A unit run must not provision — and must fail loudly if it connects."""
        from tr_shared.testing.lanes import POISON_DATABASE_URL, POISON_REDIS_URL

        project = _project(tmp_path, opted_in=True)
        result = _run_pytest(project, DOCKER_HOST="unix:///nonexistent")
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
        assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
        combined = result.stdout + result.stderr
        assert "non-local host" in combined
        assert "supabase.com" in combined

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
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
        assert _recorded(project)["DATABASE_URL"] == (f"postgresql+asyncpg://u:p@{host}:5432/db")


_LOCAL_DSN = "postgresql+asyncpg://u:p@127.0.0.1:5432/db"


class TestG1LoopbackOnly:
    @pytest.mark.parametrize("host", ["db.example.com", "postgres", "tr-test-pg-abc"])
    def test_a_remote_test_database_url_is_a_usage_error(self, tmp_path: Path, host: str) -> None:
        project = _override_project(tmp_path)
        result = _run_override(
            project, TEST_DATABASE_URL=f"postgresql+asyncpg://u:p@{host}:5432/db"
        )
        assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
        assert host in result.stdout + result.stderr

    @pytest.mark.parametrize("host", ["db.example.com", "redis"])
    def test_a_remote_test_redis_url_is_a_usage_error(self, tmp_path: Path, host: str) -> None:
        project = _override_project(tmp_path)
        result = _run_override(
            project, TEST_DATABASE_URL=_LOCAL_DSN, TEST_REDIS_URL=f"redis://{host}:6379"
        )
        assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
        assert host in result.stdout + result.stderr

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
    def test_a_loopback_test_redis_url_is_accepted(self, tmp_path: Path, host: str) -> None:
        project = _override_project(tmp_path)
        result = _run_override(
            project, TEST_DATABASE_URL=_LOCAL_DSN, TEST_REDIS_URL=f"redis://{host}:6379"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _recorded(project)["REDIS_URL"] == f"redis://{host}:6379/0"


# --------------------------------------------------------------------------- #
# The TEST_DATABASE_URL override branch (L-A / D13)
# --------------------------------------------------------------------------- #

_OVERRIDE_CONFTEST = """
import json, os, pathlib
pathlib.Path("env_at_conftest_import.json").write_text(json.dumps({
    "DATABASE_URL": os.environ.get("DATABASE_URL"),
    "REDIS_URL": os.environ.get("REDIS_URL"),
    "CELERY_BROKER_URL": os.environ.get("CELERY_BROKER_URL"),
    "CELERY_RESULT_BACKEND": os.environ.get("CELERY_RESULT_BACKEND"),
    "TR_TESTING_RUN_ID": os.environ.get("TR_TESTING_RUN_ID"),
}))
"""


def _override_project(tmp_path: Path, *, migrate_ok: bool = True, extra_toml: str = "") -> Path:
    """A project whose migrate_command is observable and can be made to fail.

    `migrate_command = ["true"]` in `_project` above cannot distinguish "migrations
    ran" from "migrations were skipped" — which is exactly the hole this branch had.
    Here the command writes a marker file, so its absence is a failing assertion
    rather than an invisible no-op.
    """
    script = tmp_path / "fake_migrate.sh"
    body = (
        'printf "%s" "$DATABASE_URL" > "$(dirname "$0")/migrated.txt"\n'
        'env > "$(dirname "$0")/migrate_env.txt"\n'
    )
    script.write_text(
        "#!/bin/sh\n" + body + ("exit 0\n" if migrate_ok else "echo 'boom' >&2\nexit 1\n")
    )
    script.chmod(0o755)

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\n'
        "[tool.tr_testing]\n"
        'service = "tr-demo"\n'
        f'migrate_command = ["{script}"]\n'
        'migration_globs = ["migrations/*.py"]\n' + extra_toml
    )
    integration = tmp_path / "tests" / "integration"
    integration.mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text(textwrap.dedent(_OVERRIDE_CONFTEST))
    (integration / "test_demo.py").write_text(textwrap.dedent(_TEST))
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001.py").write_text("revision = '1'\n")
    return tmp_path


def _run_override(project: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration/", "-q", "-p", "no:cacheprovider"],
        cwd=project,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(project), **env},
    )


class TestOverrideBranchMigrates:
    """N-1: the branch used to return before provision(), so nothing ever migrated.

    crm-core's CI took this path, had no migrate step of its own, and stayed red for
    five runs with `relation "..." does not exist` — while the workflow comment
    asserted schema construction happened elsewhere. The branch's early `return` is
    what made the failure silent.
    """

    def test_migrations_actually_run(self, tmp_path: Path) -> None:
        project = _override_project(tmp_path)
        dsn = "postgresql+asyncpg://u:p@127.0.0.1:5432/db"
        result = _run_override(project, TEST_DATABASE_URL=dsn)

        assert result.returncode == 0, result.stdout + result.stderr
        marker = project / "migrated.txt"
        assert marker.exists(), (
            "migrate_command never ran — the override branch is skipping migrations again"
        )
        assert marker.read_text() == dsn, "migrations ran against the wrong database"

    def test_a_failing_migration_aborts_the_run(self, tmp_path: Path) -> None:
        """Loud, not silent. An unmigrated database must never reach the tests."""
        project = _override_project(tmp_path, migrate_ok=False)
        result = _run_override(
            project, TEST_DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db"
        )

        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "migrations failed against TEST_DATABASE_URL" in combined
        assert "boom" in combined, "the migration tool's own stderr must be surfaced"


class TestOverrideBranchRedisIsolation:
    """N-10: cache, broker and results were all set to the same TEST_REDIS_URL."""

    def test_three_distinct_consecutive_databases(self, tmp_path: Path) -> None:
        project = _override_project(tmp_path)
        result = _run_override(
            project,
            TEST_DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
            TEST_REDIS_URL="redis://127.0.0.1:6379",
        )
        assert result.returncode == 0, result.stdout + result.stderr

        env = _recorded(project)
        urls = [env["REDIS_URL"], env["CELERY_BROKER_URL"], env["CELERY_RESULT_BACKEND"]]
        assert len(set(urls)) == 3, f"collapsed onto one Redis database: {urls}"
        assert urls == [
            "redis://127.0.0.1:6379/0",
            "redis://127.0.0.1:6379/1",
            "redis://127.0.0.1:6379/2",
        ]

    def test_an_index_on_the_supplied_url_is_replaced_not_appended(self, tmp_path: Path) -> None:
        """A CI runner naming `redis://host:6379/0` is naming a server, not an index."""
        project = _override_project(tmp_path)
        result = _run_override(
            project,
            TEST_DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
            TEST_REDIS_URL="redis://127.0.0.1:6379/9",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _recorded(project)["REDIS_URL"] == "redis://127.0.0.1:6379/0"

    def test_no_redis_url_falls_back_to_the_poison_url(self, tmp_path: Path) -> None:
        """Silently pointing at a real local Redis would be worse than failing."""
        from tr_shared.testing.lanes import POISON_REDIS_URL

        project = _override_project(tmp_path)
        result = _run_override(
            project, TEST_DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _recorded(project)["REDIS_URL"] == POISON_REDIS_URL


_HOSTILE = {
    "database_url": "postgresql://leak@db.example.com/x",
    "LANGSMITH_TRACING": "true",
    "GOOGLE_API_KEY": "leak",
    "ENVIRONMENT": "development",
    "AUTH_LIB_DEV_MODE_BYPASS": "true",
    "UV_ENV_FILE": ".env",
}

_TABLE = '\n[tool.tr_testing.env]\nDEMO_TABLE_KEY = "from-table"\n'


class TestMigrateSubprocessEnv:
    def test_table_and_policy_reach_the_migrate_subprocess(self, tmp_path: Path) -> None:
        project = _override_project(tmp_path, extra_toml=_TABLE)
        result = _run_override(project, TEST_DATABASE_URL=_LOCAL_DSN, **_HOSTILE)
        assert result.returncode == 0, result.stdout + result.stderr

        lines = (project / "migrate_env.txt").read_text().splitlines()
        env = dict(line.split("=", 1) for line in lines if "=" in line)
        assert env["DEMO_TABLE_KEY"] == "from-table"
        assert env["ENVIRONMENT"] == "test"
        assert env["DATABASE_URL"] == _LOCAL_DSN
        assert not set(_HOSTILE) - {"ENVIRONMENT"} & set(env)

    def test_an_inherited_run_id_is_not_reused_by_the_controller(self, tmp_path: Path) -> None:
        project = _override_project(tmp_path)
        result = _run_override(project, TEST_DATABASE_URL=_LOCAL_DSN, TR_TESTING_RUN_ID="stale")
        assert result.returncode == 0, result.stdout + result.stderr
        run_id = _recorded(project)["TR_TESTING_RUN_ID"]
        assert run_id and run_id != "stale"


_SCRUB_CONFTEST = """
import json, os, pathlib
role = os.environ.get("PYTEST_XDIST_WORKER", "controller")
pathlib.Path(f"env_conftest_{role}.json").write_text(json.dumps(dict(os.environ)))
"""

_SCRUB_TEST = """
import json, os, pathlib, subprocess, sys

from pkg.mod import answer


def _record():
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    pathlib.Path(f"env_test_{worker}.json").write_text(json.dumps(dict(os.environ)))
    child = subprocess.run(
        [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
        capture_output=True, text=True, check=True,
    ).stdout
    pathlib.Path(f"env_child_{worker}.json").write_text(child)


def test_one():
    _record()
    assert answer() == 42


def test_two():
    _record()
    assert answer() == 42
"""


def _scrub_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\n'
        '[tool.pytest.ini_options]\npythonpath = ["."]\n' + _OPT_IN + _TABLE
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "mod.py").write_text("def answer():\n    return 42\n")
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text(textwrap.dedent(_SCRUB_CONFTEST))
    (tests / "test_scrub.py").write_text(textwrap.dedent(_SCRUB_TEST))
    (tmp_path / "migrations").mkdir()
    return tmp_path


class TestScrub:
    def test_xdist_workers_controller_and_subprocesses_see_only_the_owned_env(
        self, tmp_path: Path
    ) -> None:
        import json

        from tr_shared.testing.config import POLICY_ENV

        project = _scrub_project(tmp_path)
        result = _run_pytest(project, "-n", "2", "--cov=pkg", "--cov-report=term", **_HOSTILE)
        assert result.returncode == 0, result.stdout + result.stderr

        recorded = {p.name: json.loads(p.read_text()) for p in project.glob("env_*.json")}
        workers = [n for n in recorded if n.startswith("env_test_gw")]
        assert "env_conftest_controller.json" in recorded
        assert workers, sorted(recorded)
        assert any(n.startswith("env_child_gw") for n in recorded)
        for name, env in recorded.items():
            assert not (set(_HOSTILE) - {"ENVIRONMENT"}) & set(env), name
            assert env["DEMO_TABLE_KEY"] == "from-table", name
            for key, value in POLICY_ENV.items():
                assert env[key] == value, (name, key)

        cov_line = next(line for line in result.stdout.splitlines() if "pkg/mod.py" in line)
        assert cov_line.rstrip().endswith("100%"), result.stdout
