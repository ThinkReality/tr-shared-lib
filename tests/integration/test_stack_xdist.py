"""The stack under pytest-xdist: one container, one template, a database per worker.

This is the property the design turns on, and it is the one that cannot be
checked by reading code. pytest-xdist runs each worker as its own process with
its own session, so a naive session-scoped fixture starts **one container per
worker** — on a 12-core machine that is twelve Postgres containers and twelve
full migration runs (measured: ~6s + ~11.5s each for tr-crm-core) before the
first assertion. A filelock elects one provisioner; everyone else attaches.

The second property is ``CREATE DATABASE … TEMPLATE``, which fails outright while
any session is connected to the template. That is why every administrative
statement in ``stack.py`` runs through ``docker exec … psql`` rather than a
host-side engine whose pool outlives the call.

Requires Docker. Skipped — not failed — when it is absent, because this file
tests the provisioner itself rather than a service's behaviour; a service suite
that cannot reach its database is a hard failure (see the standard, §1).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker is not reachable"
)

_PYPROJECT = """
[project]
name = "demo"
version = "0"

[tool.tr_testing]
service = "tr-xdist-demo"
migrate_command = ["python", "migrate.py"]
migration_globs = ["migrations/*.sql"]
"""

# Stands in for `alembic upgrade head`: it must leave a recognisable schema in
# the database the plugin points it at, so the clones can be proven to descend
# from the template rather than from an empty database.
_MIGRATE = """
import os, sys, urllib.parse as up, subprocess
dsn = os.environ["DATABASE_URL"]
parsed = up.urlsplit(dsn)
db = parsed.path.lstrip("/")
sql = "CREATE TABLE migrated_marker (id int primary key); INSERT INTO migrated_marker VALUES (1);"
subprocess.run(
    ["docker", "exec", os.environ["TR_PG_CONTAINER"], "psql", "-v", "ON_ERROR_STOP=1",
     "-U", "postgres", "-d", db, "-c", sql],
    check=True,
)
"""

_CONFTEST = """
import json, os, pathlib, uuid

def pytest_sessionfinish(session, exitstatus):
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    pathlib.Path(f"seen_{worker}.json").write_text(json.dumps({
        "database_url": os.environ.get("DATABASE_URL"),
        "redis_url": os.environ.get("REDIS_URL"),
        "run_id": os.environ.get("TR_TESTING_RUN_ID"),
    }))
"""

_TEST_FILE = """
def test_one(): assert True
def test_two(): assert True
def test_three(): assert True
def test_four(): assert True
def test_five(): assert True
def test_six(): assert True
def test_seven(): assert True
def test_eight(): assert True
"""


def _project(tmp_path: Path, token: str) -> Path:
    """A project whose fingerprint is unique to `token`.

    Each test needs its OWN container and template. Sharing them would make
    these tests order-dependent on each other — the reuse test mutates its
    template on purpose, which would then break the test above it. Writing a
    fingerprint-relevant file per test is the same "purpose-built data" rule the
    standard applies to database rows.
    """
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    (tmp_path / "migrate.py").write_text(textwrap.dedent(_MIGRATE))
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001.sql").write_text(f"-- baseline {token}\n")
    tests = tmp_path / "tests" / "integration"
    tests.mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text(textwrap.dedent(_CONFTEST))
    (tests / "test_demo.py").write_text(textwrap.dedent(_TEST_FILE))
    return tmp_path


def _key(project: Path) -> str:
    from tr_shared.testing.config import find_config

    config = find_config(project)
    assert config is not None
    return config.key[:10]


def _psql(container: str, sql: str, database: str = "postgres") -> str:
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-tAc", sql, "-U", "postgres", "-d", database],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def cleanup_containers():
    """Remove the containers a test created. They are reusable by design, so
    nothing else will."""
    keys: list[str] = []
    yield keys
    for key in keys:
        for kind in ("pg", "redis"):
            subprocess.run(
                ["docker", "rm", "-f", f"tr-test-{kind}-{key}"],
                capture_output=True,
                text=True,
            )


@requires_docker
class TestOneContainerServesEveryWorker:
    def test_four_workers_share_one_container_and_template(
        self, tmp_path: Path, cleanup_containers: list[str]
    ) -> None:
        project = _project(tmp_path, "xdist")
        key = _key(project)
        cleanup_containers.append(key)
        pg_container = f"tr-test-pg-{key}"

        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "tests/integration/",
                "-q", "-p", "no:cacheprovider", "-n", "4",
            ],
            cwd=project,
            capture_output=True,
            text=True,
            env={
                "PATH": f"/usr/local/bin:/usr/bin:/bin:{Path(sys.executable).parent}",
                "HOME": str(project),
                "TR_PG_CONTAINER": pg_container,
            },
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "8 passed" in result.stdout

        # 1. Exactly one Postgres container exists for this key — not one per worker.
        containers = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={pg_container}", "--format", "{{.Names}}"],
            capture_output=True, text=True,
        ).stdout.split()
        assert containers == [pg_container], containers

        # 2. Exactly one template, built once.
        templates = _psql(
            pg_container,
            "SELECT datname FROM pg_database WHERE datname LIKE '%_tmpl_%' "
            f"AND datname LIKE '%{key}%'",
        ).split()
        assert len(templates) == 1, templates

        # 3. The template really was migrated (the clone source is not empty).
        marker = _psql(pg_container, "SELECT count(*) FROM migrated_marker", templates[0])
        assert marker == "1"

        # 4. Every worker got a DISTINCT database and a distinct Redis index,
        #    and all shared one run id.
        seen = [json.loads(p.read_text()) for p in project.glob("seen_gw*.json")]
        assert len(seen) == 4, seen
        assert len({s["database_url"] for s in seen}) == 4
        assert len({s["redis_url"] for s in seen}) == 4
        assert len({s["run_id"] for s in seen}) == 1

        # 5. Worker databases are dropped at session end; the template survives
        #    so the next run is fast.
        leftovers = _psql(
            pg_container,
            f"SELECT datname FROM pg_database WHERE datname LIKE '%{key}%' "
            "AND datname NOT LIKE '%_tmpl_%'",
        ).split()
        assert leftovers == [], leftovers

    def test_second_run_reuses_the_container_and_template(
        self, tmp_path: Path, cleanup_containers: list[str]
    ) -> None:
        """Warm server, cold data: the template is not rebuilt, the data is fresh."""
        project = _project(tmp_path, "reuse")
        key = _key(project)
        cleanup_containers.append(key)
        pg_container = f"tr-test-pg-{key}"
        env = {
            "PATH": f"/usr/local/bin:/usr/bin:/bin:{Path(sys.executable).parent}",
            "HOME": str(project),
            "TR_PG_CONTAINER": pg_container,
        }
        cmd = [sys.executable, "-m", "pytest", "tests/integration/", "-q", "-p", "no:cacheprovider"]

        first = subprocess.run(cmd, cwd=project, capture_output=True, text=True, env=env)
        assert first.returncode == 0, first.stdout + first.stderr
        created = _psql(pg_container, "SELECT count(*) FROM pg_database WHERE datname LIKE '%_tmpl_%'")

        # Prove reuse rather than rebuild: drop the marker's row. A rebuilt
        # template would restore it; a reused one will not.
        templates = _psql(
            pg_container,
            f"SELECT datname FROM pg_database WHERE datname LIKE '%{key}%' AND datname LIKE '%_tmpl_%'",
        ).split()
        _psql(pg_container, "DELETE FROM migrated_marker", templates[0])

        second = subprocess.run(cmd, cwd=project, capture_output=True, text=True, env=env)
        assert second.returncode == 0, second.stdout + second.stderr
        assert _psql(pg_container, "SELECT count(*) FROM pg_database WHERE datname LIKE '%_tmpl_%'") == created
        assert _psql(pg_container, "SELECT count(*) FROM migrated_marker", templates[0]) == "0"
