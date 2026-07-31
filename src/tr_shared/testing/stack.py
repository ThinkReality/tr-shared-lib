"""Postgres and Redis for a test run: warm server, cold data.

Two properties have to hold at once, and they pull in opposite directions:

* **Fresh data every run.** Cross-run residue is not hypothetical — it made
  tr-crm-core's suite report 119 failures from a cold database and 48 from a warm
  one, for months, with no code change in between.
* **A fast local loop.** Starting a container costs ~6s and migrating
  tr-crm-core's six Alembic trees costs ~11.5s. Paying ~17.5s before every
  targeted test is how a standard gets worked around.

So the **server** is reused across runs and the **database** never is:

    container   tr-test-pg-<key>          reused; keyed on a hash of the
                                          migration files, so a migration change
                                          mints a new container
    template    <svc>_tmpl_<key>          migrated once per key, then reused
    run db      <svc>_<key>_<run>_<wrk>   cloned from the template per xdist
                                          worker, dropped at session end

Why the docker SDK rather than testcontainers: testcontainers-python 4.14.2 has
no container reuse (it is a Java/Go feature — the Python package contains no
implementation of it), and reuse is the entire point of the split above.

**All administrative DDL runs through ``docker exec … psql`` inside the
container.** That is not a style choice. ``CREATE DATABASE … TEMPLATE`` fails
outright while *any* session is connected to the template, and a host-side
SQLAlchemy engine keeps its pool open long after the call that used it returned.
Running the DDL inside the container means the only connection is psql's own, and
it is gone when the exec returns.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tr_shared.testing.config import TestingConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

__all__ = [
    "REUSE_LABEL",
    "Stack",
    "StackError",
    "drop_run_databases",
    "provision",
]

#: Every container this module creates carries it, so cleanup is one command:
#: ``docker rm -f $(docker ps -aq -f label=tr.testing=1)``
REUSE_LABEL = {"tr.testing": "1"}

_POSTGRES_SUPERUSER = "postgres"
_POSTGRES_PASSWORD = "test"
_READY_TIMEOUT_SECONDS = 60
# Consecutive successes required before a container counts as ready, and the gap
# between probes. See _wait_ready for why one success is not enough.
_READY_STREAK = 3
_READY_INTERVAL_SECONDS = 0.3
_PG_IDENTIFIER_MAX = 63


class StackError(RuntimeError):
    """Infrastructure could not be provisioned.

    Always raised, never turned into a skip: a suite that skips itself when its
    database is missing reports success for tests that never ran.
    """


@dataclass(frozen=True)
class Stack:
    postgres_dsn: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str


def _docker() -> Any:
    try:
        import docker
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise StackError(
            "The integration lane needs the 'testing' extra: "
            "add tr-shared-lib[testing] to your dev dependencies."
        ) from exc
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        raise StackError(
            "Docker is required for the integration lane and is not reachable. "
            "Start Docker, or run only the unit lane (pytest tests/unit/), which "
            "needs no containers."
        ) from exc
    return client


def _sanitize(value: str) -> str:
    """Postgres identifiers and container names tolerate a narrower alphabet."""
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def _lock(name: str) -> Any:
    """Cross-process lock, so exactly one xdist worker provisions.

    pytest-xdist runs each worker as its own process with its own session, so a
    session-scoped fixture runs once *per worker*. Without this, ``-n auto`` on a
    12-core machine starts twelve containers and runs twelve full migrations.
    """
    try:
        from filelock import FileLock
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise StackError(
            "The integration lane needs the 'testing' extra (filelock is missing)."
        ) from exc
    lock_dir = Path(tempfile.gettempdir()) / "tr-testing-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return FileLock(str(lock_dir / f"{name}.lock"), timeout=300)


def _ensure_container(
    client: Any,
    *,
    name: str,
    image: str,
    container_port: int,
    environment: dict[str, str],
    command: list[str] | None,
    ready_probe: list[str],
) -> int:
    """Adopt the named container if it exists, otherwise create it. Return host port."""
    import docker.errors

    if os.environ.get("TR_TESTING_FRESH"):
        try:
            client.containers.get(name).remove(force=True)
        except docker.errors.NotFound:
            pass
        _await_gone(client, name)

    container = _adopt_or_create(
        client,
        name=name,
        image=image,
        container_port=container_port,
        environment=environment,
        command=command,
    )
    container.reload()
    bindings = container.ports.get(f"{container_port}/tcp")
    if not bindings:
        raise StackError(f"{name} exposes no host port for {container_port}")
    host_port = int(bindings[0]["HostPort"])

    _wait_ready(container, ready_probe, name)
    return host_port


def _await_gone(client: Any, name: str, timeout: float = 20.0) -> None:
    """Wait for a container name to become free.

    ``docker rm -f`` returns before the container is gone: it lingers in
    ``removing`` state, where ``containers.get()`` still finds it but starting it
    fails and creating one with the same name conflicts. Running two suites
    back-to-back hit this roughly one time in four.
    """
    import docker.errors

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            client.containers.get(name)
        except docker.errors.NotFound:
            return
        time.sleep(0.2)


def _adopt_or_create(
    client: Any,
    *,
    name: str,
    image: str,
    container_port: int,
    environment: dict[str, str],
    command: list[str] | None,
    attempts: int = 3,
) -> Any:
    """Attach to the named container, or create it. Retries the racy states.

    Two processes can interleave here even under the filelock — a stale lock
    directory, a second checkout, or a container mid-removal from a previous run.
    Every one of those resolves by looking again, so they are retried rather than
    raised.
    """
    import docker.errors

    last: Exception | None = None
    for _ in range(attempts):
        try:
            container = client.containers.get(name)
            if container.status == "removing":
                _await_gone(client, name)
                continue
            if container.status != "running":
                # A stopped container keeps its data, and that data is a previous
                # run's template — still valid, because the key covers migrations.
                container.start()
            return container
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError as exc:
            last = exc

        try:
            return client.containers.run(
                image,
                command=command,
                name=name,
                detach=True,
                environment=environment,
                ports={f"{container_port}/tcp": None},
                labels=REUSE_LABEL,
            )
        except docker.errors.APIError as exc:
            last = exc
            if "Conflict" not in str(exc) and "already in use" not in str(exc):
                raise StackError(f"could not start {name}: {exc}") from exc
            # Someone else created it between our get() and run(); go round again.

    raise StackError(f"could not obtain container {name} after {attempts} attempts: {last}")


def _wait_ready(container: Any, probe: list[str], name: str) -> None:
    """Wait until the probe succeeds ``_READY_STREAK`` times in a row.

    A single success is not enough, and this is not defensive padding. The
    official Postgres image runs initdb against a **temporary** server, then
    stops it and starts the real one. ``pg_isready`` returns 0 against that
    temporary server, so a first-success probe returns during the gap and the
    very next statement fails with::

        psql: error: connection to server on socket
        "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory

    Observed roughly one run in four, and only ever on a freshly created
    container — which is exactly the case a reuse-based design makes rare enough
    to look like flakiness.
    """
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    streak = 0
    last = ""
    while time.monotonic() < deadline:
        try:
            result = container.exec_run(probe)
            if result.exit_code == 0:
                streak += 1
                if streak >= _READY_STREAK:
                    return
            else:
                streak = 0
                last = result.output.decode(errors="replace").strip()
        except Exception as exc:  # container still booting
            streak = 0
            last = str(exc)
        time.sleep(_READY_INTERVAL_SECONDS)
    raise StackError(f"{name} did not become ready in {_READY_TIMEOUT_SECONDS}s: {last}")


def _psql(container: Any, sql: str, *, database: str = "postgres") -> str:
    """Run one statement inside the container.

    ``--no-psqlrc`` and ``ON_ERROR_STOP`` so a failure is a failure rather than a
    zero exit with an error printed to stdout.
    """
    result = container.exec_run(
        [
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "--no-psqlrc",
            "-U",
            _POSTGRES_SUPERUSER,
            "-d",
            database,
            "-tAc",
            sql,
        ]
    )
    output = str(result.output.decode(errors="replace")).strip()
    if result.exit_code != 0:
        raise StackError(f"psql failed ({sql.splitlines()[0][:80]}…): {output}")
    return output


def _database_exists(container: Any, name: str) -> bool:
    found = _psql(container, f"SELECT 1 FROM pg_database WHERE datname = '{name}'")
    return found == "1"


def run_migrations(config: TestingConfig, dsn: str) -> subprocess.CompletedProcess[str]:
    """Run the service's own ``migrate_command`` against ``dsn``.

    Shared by the container path (which builds a template) and the plugin's
    ``TEST_DATABASE_URL`` override path. It lives here as one function because the
    override path originally had **no** migration step at all: it returned before
    ``provision()``, so the database was never migrated, and crm-core's CI stayed red
    for five runs while every doc claimed the suite was green. Two copies of "how this
    service migrates" is how that happens again.

    Resolving the executable against the service's own ``.venv/bin`` matters: the
    command is usually ``alembic`` or a project console script, which is not on PATH in
    a bare CI shell.

    Returns the completed process rather than raising, because the two callers clean up
    differently — the container path drops its half-built database first.
    """
    executable = shutil.which(
        config.migrate_command[0],
        path=os.pathsep.join(
            [str(Path(config.root) / ".venv" / "bin"), os.environ.get("PATH", "")]
        ),
    )
    command = [executable or config.migrate_command[0], *config.migrate_command[1:]]
    return subprocess.run(
        command,
        cwd=config.root,
        env={**os.environ, "DATABASE_URL": dsn, "ENVIRONMENT": "test"},
        capture_output=True,
        text=True,
    )


def redis_triple(base_url: str, worker_id: str) -> tuple[str, str, str]:
    """``(cache, broker, results)`` on three consecutive database indexes.

    Any database index already on ``base_url`` is discarded — the caller is naming a
    server, and the index is this function's to assign.

    Split out so the ``TEST_DATABASE_URL`` override path cannot quietly lose the
    isolation the container path is careful to provide. It used to set all three to the
    same ``TEST_REDIS_URL``, which puts Celery's broker, its result backend and the
    application cache in one database: a ``flushdb`` between tests then wipes queued
    tasks, and a key collision across the three is indistinguishable from a bug.
    """
    server = re.sub(r"/\d+/?$", "", base_url.rstrip("/"))
    index = _redis_index(worker_id)
    return (f"{server}/{index}", f"{server}/{index + 1}", f"{server}/{index + 2}")


def _build_template(
    container: Any,
    config: TestingConfig,
    template: str,
    host_port: int,
) -> None:
    """Migrate a fresh database, then rename it into place.

    The rename is what makes this crash-safe. Migrating directly into the
    template name would leave a half-built template behind if the migration
    failed or the run was interrupted — and the next run would find it, consider
    it ready, and clone a broken schema into every worker.
    """
    building = f"{template}_building"
    _psql(container, f'DROP DATABASE IF EXISTS "{building}" WITH (FORCE)')
    _psql(container, f'CREATE DATABASE "{building}"')
    for extension in config.extensions:
        _psql(container, f"CREATE EXTENSION IF NOT EXISTS {extension}", database=building)

    dsn = _dsn(host_port, building)
    result = run_migrations(config, dsn)
    if result.returncode != 0:
        _psql(container, f'DROP DATABASE IF EXISTS "{building}" WITH (FORCE)')
        raise StackError(
            f"migrations failed while building the test template "
            f"({' '.join(config.migrate_command)}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    # The migration process has exited, so nothing holds `building` open.
    _psql(container, f'ALTER DATABASE "{building}" RENAME TO "{template}"')


def _dsn(host_port: int, database: str) -> str:
    return (
        f"postgresql+asyncpg://{_POSTGRES_SUPERUSER}:{_POSTGRES_PASSWORD}"
        f"@127.0.0.1:{host_port}/{database}"
    )


def _names(config: TestingConfig, run_id: str, worker_id: str) -> tuple[str, str, str]:
    service = _sanitize(config.service)[:16]
    key = config.key[:10]
    template = f"{service}_tmpl_{key}"
    run_db = f"{service}_{key}_{_sanitize(run_id)[:10]}_{_sanitize(worker_id)[:6]}"
    if len(run_db) > _PG_IDENTIFIER_MAX:  # pragma: no cover - names are bounded above
        run_db = run_db[:_PG_IDENTIFIER_MAX]
    return f"tr-test-pg-{key}", template, run_db


def provision(config: TestingConfig, run_id: str, worker_id: str) -> Stack:
    """Containers up, template built if needed, this worker's database cloned."""
    client = _docker()
    pg_name, template, run_db = _names(config, run_id, worker_id)
    redis_name = f"tr-test-redis-{config.key[:10]}"

    with _lock(pg_name):
        pg_port = _ensure_container(
            client,
            name=pg_name,
            image=config.postgres_image,
            container_port=5432,
            environment={
                "POSTGRES_USER": _POSTGRES_SUPERUSER,
                "POSTGRES_PASSWORD": _POSTGRES_PASSWORD,
                "POSTGRES_DB": _POSTGRES_SUPERUSER,
            },
            command=None,
            ready_probe=[
                "psql",
                "-U",
                _POSTGRES_SUPERUSER,
                "-d",
                _POSTGRES_SUPERUSER,
                "-tAc",
                "SELECT 1",
            ],
        )
        container = client.containers.get(pg_name)
        if not _database_exists(container, template):
            _build_template(container, config, template, pg_port)

        _psql(container, f'DROP DATABASE IF EXISTS "{run_db}" WITH (FORCE)')
        _psql(container, f'CREATE DATABASE "{run_db}" TEMPLATE "{template}"')

    with _lock(redis_name):
        redis_port = _ensure_container(
            client,
            name=redis_name,
            image=config.redis_image,
            container_port=6379,
            environment={},
            # 16 databases is the Redis default, and D8 gives each xdist worker
            # its own index for cache, broker and result backend — three each,
            # which caps the run at five workers. 64 costs nothing.
            command=["redis-server", "--databases", "64", "--save", ""],
            ready_probe=["redis-cli", "ping"],
        )

    cache_url, broker_url, result_url = redis_triple(f"redis://127.0.0.1:{redis_port}", worker_id)
    return Stack(
        postgres_dsn=_dsn(pg_port, run_db),
        redis_url=cache_url,
        celery_broker_url=broker_url,
        celery_result_backend=result_url,
    )


def _redis_index(worker_id: str) -> int:
    """Three consecutive database indexes per worker: cache, broker, results.

    Redis pub/sub channels are global to the *server*, not the database index, so
    this isolates keys but not channels. Nothing in the fleet subscribes during
    tests today; when something does, it needs a per-run channel prefix, not a
    bigger index space.
    """
    digits = re.sub(r"\D", "", worker_id)
    slot = int(digits) if digits else 0
    return (slot * 3) % 60


def drop_run_databases(config: TestingConfig, run_id: str, worker_id: str) -> None:
    """Drop this worker's cloned database. The container and template survive."""
    try:
        client = _docker()
        pg_name, _, run_db = _names(config, run_id, worker_id)
        container = client.containers.get(pg_name)
        _psql(container, f'DROP DATABASE IF EXISTS "{run_db}" WITH (FORCE)')
    except Exception:
        # Teardown must never turn a green run red. A leaked clone is dropped by
        # the next run that uses the same name, and by `docker rm -f` on the
        # container itself.
        return
