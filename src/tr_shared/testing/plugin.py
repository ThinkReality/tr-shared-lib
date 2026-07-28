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


def pytest_load_initial_conftests(
    early_config: Any, parser: Any, args: list[str]
) -> None:
    config = find_config(Path(early_config.rootdir))
    if config is None:
        return  # not opted in — do nothing at all

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

    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        _assert_local(override)
        _export(
            database_url=override,
            redis_url=os.environ.get("TEST_REDIS_URL", POISON_REDIS_URL),
            broker_url=os.environ.get("TEST_REDIS_URL", POISON_REDIS_URL),
            result_backend=os.environ.get("TEST_REDIS_URL", POISON_REDIS_URL),
        )
        return

    from tr_shared.testing.stack import provision

    run_id = _run_id()
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
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


def _export(
    *, database_url: str, redis_url: str, broker_url: str, result_backend: str
) -> None:
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
