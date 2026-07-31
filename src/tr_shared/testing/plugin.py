"""The ``pytest11`` plugin: resolves the lane, provisions it, exports the env.

**Timing is the whole design.** Every service builds its SQLAlchemy engine at
import time from an ``lru_cache``d ``get_settings()``, so ``DATABASE_URL`` must be
correct before the first ``app.*`` import — which happens inside
``tests/conftest.py``. Measured hook order:

    [plugin MODULE import]
    [pytest_load_initial_conftests]   <- env set here; args and -m are available
    [tests/conftest.py TOP]
    [pytest_configure]
    [test module import]

``pytest_configure`` is far too late. A plugin declared via ``pytest_plugins`` in
a conftest is also too late — it imports *after* that conftest has finished
executing. Only an entry-point plugin runs early enough, and only
``pytest_load_initial_conftests`` runs early enough *and* can see what was asked
for, which is what lets the unit lane skip Docker entirely.

The plugin is inert unless the service declares ``[tool.tr_testing]``
(see ``config.py``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tr_shared.testing.config import TestingConfig, find_config
from tr_shared.testing.lanes import (
    POISON_DATABASE_URL,
    POISON_REDIS_URL,
    lane_for_path,
    run_needs_infrastructure,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pytest

__all__ = ["pytest_collection_modifyitems", "pytest_load_initial_conftests"]

_STATE: dict[str, Any] = {}


def pytest_load_initial_conftests(early_config: Any, parser: Any, args: list[str]) -> None:
    config = find_config(Path(early_config.rootdir))
    if config is None:
        return  # not opted in — do nothing at all

    _assert_venv_belongs_to_this_service(Path(early_config.rootdir))

    _STATE["config"] = config
    needs_infra = run_needs_infrastructure(args, _markexpr(early_config))
    _STATE["lane"] = "integration" if needs_infra else "unit"

    os.environ.setdefault("ENVIRONMENT", "test")
    if not needs_infra:
        _export(
            database_url=POISON_DATABASE_URL,
            redis_url=POISON_REDIS_URL,
            broker_url=POISON_REDIS_URL,
            result_backend=POISON_REDIS_URL,
        )
        return

    run_id = _run_id()
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")

    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        _assert_local(override)
        _use_override(config, override, worker_id)
        return

    from tr_shared.testing.stack import provision

    stack = provision(config, run_id, worker_id)
    _STATE["run_id"] = run_id
    _STATE["worker_id"] = worker_id
    _export(
        database_url=stack.postgres_dsn,
        redis_url=stack.redis_url,
        broker_url=stack.celery_broker_url,
        result_backend=stack.celery_result_backend,
    )


def pytest_configure(config: Any) -> None:
    """Register the derived markers, but only for an opted-in service.

    Registering them unconditionally would be a visible side effect in the seven
    services that have not adopted — which is precisely what "inert" forbids.
    """
    if _STATE.get("config") is None:
        return
    for lane in ("unit", "integration", "e2e"):
        config.addinivalue_line("markers", f"{lane}: derived from the test's path")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Derive the lane marker from the path.

    Hand-applied markers drift from the directory they describe; derived ones
    cannot. This mirrors what tr-whatsApp-marketing-agent already did locally —
    the pattern was right, it was just living in one service's conftest.

    Inert for a service that has not opted in: marking another service's items
    would change its `-m` selections without anyone asking.
    """
    if _STATE.get("config") is None:
        return
    for item in items:
        lane = lane_for_path(str(item.fspath))
        if lane:
            item.add_marker(lane)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    config: TestingConfig | None = _STATE.get("config")
    if config is None or "run_id" not in _STATE:
        return
    from tr_shared.testing.stack import drop_run_databases

    drop_run_databases(config, _STATE["run_id"], _STATE["worker_id"])


def _use_override(config: TestingConfig, dsn: str, worker_id: str) -> None:
    """Point the run at a caller-supplied database, and finish the job.

    ``TEST_DATABASE_URL`` is the documented no-Docker escape hatch (D2) for CI runners
    that provide their own Postgres service. It used to do two things wrong, both of
    which this function exists to fix:

    **It never migrated.** The branch returned before ``provision()``, and
    ``provision()`` is what runs the service's ``migrate_command``. The database was
    therefore empty. crm-core's CI took this branch, had no ``migrate`` step of its own,
    and stayed red for five consecutive runs with ``relation "..." does not exist``
    while its workflow comment claimed schema construction was handled elsewhere. The
    branch reported success by returning early, which is the worst possible failure
    shape: silent.

    **It collapsed three Redis databases into one.** Cache, Celery broker and Celery
    result backend were all set to ``TEST_REDIS_URL``. The container path deliberately
    hands out three consecutive indexes; this path lost that, so a ``flushdb`` between
    tests could drop queued tasks and a key collision across the three looked like an
    application bug.

    Migrating is not conditional on the database looking empty. Alembic is idempotent —
    an already-migrated database is a no-op ``upgrade head`` — and "skip if it looks
    done" is the heuristic that produced the original bug.
    """
    from tr_shared.testing.stack import StackError, redis_triple, run_migrations

    result = run_migrations(config, dsn)
    if result.returncode != 0:
        raise StackError(
            "migrations failed against TEST_DATABASE_URL "
            f"({' '.join(config.migrate_command)}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    base = os.environ.get("TEST_REDIS_URL")
    if base:
        cache_url, broker_url, result_backend = redis_triple(base, worker_id)
    else:
        cache_url = broker_url = result_backend = POISON_REDIS_URL

    _export(
        database_url=dsn,
        redis_url=cache_url,
        broker_url=broker_url,
        result_backend=result_backend,
    )


def _export(*, database_url: str, redis_url: str, broker_url: str, result_backend: str) -> None:
    # Assignment, not setdefault. The plugin is the single owner of these values;
    # a stale export in the developer's shell is exactly the leak path that makes
    # a "local" suite talk to a remote database.
    os.environ["DATABASE_URL"] = database_url
    os.environ["REDIS_URL"] = redis_url
    os.environ["CELERY_BROKER_URL"] = broker_url
    os.environ["CELERY_RESULT_BACKEND"] = result_backend


def _markexpr(early_config: Any) -> str:
    try:
        return str(early_config.known_args_namespace.markexpr or "")
    except AttributeError:  # pragma: no cover - defensive
        return ""


def _run_id() -> str:
    """One id for the whole run, shared by every xdist worker.

    The controller sets it before workers are spawned; execnet passes the parent
    environment through, so every worker reads the same value and derives a
    database name that is unique per (run, worker).
    """
    existing = os.environ.get("TR_TESTING_RUN_ID")
    if existing:
        return existing
    run_id = str(os.getpid())
    os.environ["TR_TESTING_RUN_ID"] = run_id
    return run_id


def _assert_venv_belongs_to_this_service(rootdir: Path) -> None:
    """G14: run the repo's own ``.venv``, or stop — never another service's.

    This monorepo holds eight services side by side, each with its own ``.venv``. A
    developer who has activated one of them (or whose editor did it for them) exports
    ``VIRTUAL_ENV`` and puts that venv's ``bin/`` on ``PATH``. ``uv run pytest`` in a
    *different* service then resolves the ``pytest`` executable out of the activated
    venv, and the whole session imports from its ``site-packages``.

    Nothing announces this. It surfaces only where the two dependency sets differ, as an
    ``ImportError`` for a package that is installed, correctly, right where it belongs —
    tr-people-finance reported 74 collection errors for a missing ``email_validator``
    that was present in its own venv the entire time, because the run was using
    tr-media-service's. The traceback names the other service's path, which is the only
    clue, and it is easy to read past.

    Skipped when the repo has no ``.venv``: Docker images and CI install into the system
    environment, and there is nothing to disagree with there.
    """
    venv = rootdir / ".venv"
    if not venv.is_dir():
        return

    prefix = Path(sys.prefix).resolve()
    if prefix == venv.resolve():
        return

    raise SystemExit(
        f"Refusing to run: this is {rootdir.name}, but the interpreter belongs to "
        f"{prefix}.\n"
        f"Expected {venv.resolve()}.\n"
        "Another service's venv is active, so imports resolve against its "
        "site-packages and any failure will name a dependency that is not actually "
        "missing. Run `deactivate`, or drop the stale entry from PATH/VIRTUAL_ENV."
    )


def _assert_local(dsn: str) -> None:
    """G1: a test DSN that is not local is a hard failure, never a skip.

    The realistic leak is not a hardcoded cloud DSN — root conftests already
    refuse to load ``.env`` into the environment. It is a developer with
    ``DATABASE_URL`` exported in their shell, which defeats every
    ``os.environ.setdefault`` in the fleet. Test fixtures ``TRUNCATE`` and
    ``DROP DATABASE``; the cloud database is the only live environment there is.
    """
    from urllib.parse import urlsplit

    host = (urlsplit(dsn).hostname or "").lower()
    allowed = {"localhost", "127.0.0.1", "::1", "postgres", "postgres-test", "db"}
    if host in allowed or host.startswith("tr-test-"):
        return
    raise SystemExit(
        f"TEST_DATABASE_URL points at a non-local host ({host!r}). Refusing to run: "
        "test fixtures TRUNCATE and DROP DATABASE, and the remote database is the "
        "only live environment we have. Unset it to use a container."
    )
