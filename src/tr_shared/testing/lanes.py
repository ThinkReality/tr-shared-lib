"""Which lane a test run is in, decided by path — never by a flag.

Two lanes (``docs/shared/TR_Testing_Standard.md`` §2):

* **unit** — no database, no Redis, no Docker.
* **integration** — real containers, Docker required.

The directory decides. A marker is *derived* from the path, never hand-applied,
because a hand-applied marker is a thing to forget and an opt-out flag
(``-m "not needs_db"``) is a thing to mistype.

A unit run is given a **poison DSN** rather than no DSN at all. Format-valid, so
settings validation passes and ``create_async_engine`` constructs normally — it
does not connect. The moment a unit test opens a connection it fails on
``127.0.0.1:1`` instantly. An *absent* ``DATABASE_URL`` would instead produce a
confusing pydantic error, and the obvious "fix" for that is to point the unit
lane at a database, which is the failure this whole design exists to prevent.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

__all__ = [
    "INTEGRATION_DIRS",
    "POISON_DATABASE_URL",
    "POISON_REDIS_URL",
    "UNIT_DIRS",
    "lane_for_path",
    "run_needs_infrastructure",
]

# Port 1 is reserved (tcpmux) and never bound, so a connection attempt is refused
# immediately rather than hanging. The username and database name are there to
# make the failure self-describing in a stack trace.
POISON_DATABASE_URL = "postgresql+asyncpg://tr-unit-lane:x@127.0.0.1:1/unit_lane_no_db"
POISON_REDIS_URL = "redis://127.0.0.1:1/0"

#: Path segments whose tests never get infrastructure.
UNIT_DIRS = frozenset({"unit", "architecture", "contract", "contracts"})

#: Path segments whose tests require it.
INTEGRATION_DIRS = frozenset({"integration", "api", "e2e", "migrations", "load"})


def lane_for_path(path: str) -> str | None:
    """``"unit"``, ``"integration"``, or ``None`` when the path says neither.

    Matches on any segment, so both layouts in the fleet work:
    ``tests/unit/services/`` and ``tests/finance/unit/`` both resolve to unit.

    Integration wins ties. ``tests/integration/unit_helpers/`` is a contrived
    path, but if it ever exists, provisioning infrastructure for a test that does
    not need it costs a few seconds — withholding it from one that does is a
    confusing failure in someone else's suite.
    """
    segments = set(PurePosixPath(path.replace("\\", "/")).parts)
    if segments & INTEGRATION_DIRS:
        return "integration"
    if segments & UNIT_DIRS:
        return "unit"
    return None


def run_needs_infrastructure(
    args: list[str], markexpr: str = "", *, root: Path | None = None
) -> bool:
    """Whether this invocation must provision Postgres and Redis.

    Conservative by design: infrastructure is withheld **only** when every path
    argument is positively identified as unit. A bare ``pytest`` provisions,
    because it collects everything.

    An argument counts as a path only if it **exists on disk**. Dropping
    everything that starts with ``-`` is not enough: option *values* are separate
    argv entries, so ``-p no:cacheprovider`` offers ``no:cacheprovider`` and
    ``-k some_name`` offers ``some_name``. Both were classified as unrecognised
    paths, which forced provisioning for every unit run that passed any
    value-taking flag — i.e. most of them.

    Checking existence needs no list of value-taking options, and stays correct
    when pytest adds one.

    ``markexpr`` is accepted but **does not override the paths**, and is therefore
    no longer consulted. It used to short-circuit to ``True``, so
    ``pytest tests/unit/ -m integration`` provisioned a container for a run that can
    select nothing: the lane marker is derived from the path
    (``plugin.pytest_collection_modifyitems``), so no test under a unit path carries
    the integration marker. That cost tr-shared-lib's own unit lane ~90s per run and
    failed outright whenever the Docker daemon was busy.

    The parameter stays in the signature because the plugin passes it and it keeps
    the regression explicit in the tests. A bare ``pytest -m integration`` still
    provisions — not because of the marker, but because it names no paths.
    """
    base = root or Path.cwd()
    paths = []
    for arg in args:
        if arg.startswith("-"):
            continue
        # Strip ::TestClass::test_name selectors before classifying.
        candidate = arg.split("::", 1)[0]
        if candidate and (base / candidate).exists():
            paths.append(candidate)

    # Every path positively identified as unit — nothing else can be selected,
    # whatever the marker expression says.
    if paths and {lane_for_path(p) for p in paths} == {"unit"}:
        return False

    # Otherwise the paths are absent, mixed, or unclassified: provision.
    return True
