"""Per-test isolation: savepoint rollback for sessions, a Redis index per worker.

Two mechanisms, and the split is forced rather than stylistic:

* **A test that holds the session itself** (repository and service layers) runs
  inside an outer transaction that is rolled back afterwards. Nothing it wrote is
  ever visible to another test, and no cleanup code has to enumerate tables.
* **A test that goes through the ASGI app** cannot use that, because the app
  opens its *own* connections from a module-level sessionmaker — they are not
  part of the test's transaction, so a rollback does not reach them. Those tests
  get their own database instead, cloned per xdist worker by ``stack.provision``.

Redis needs the same treatment and did not have it: one service asserts on
relative ``XLEN`` deltas of the shared ``tr_event_bus`` stream while running under
``-n auto``, which two workers on one index make nondeterministic. The plugin
assigns three consecutive database indexes per worker (cache, broker, results).

What NOT to write instead: a global autouse ``TRUNCATE`` before every test. It
makes every test depend on collection order, hides coupling between tests, and is
how a suite starts passing only on residue left by the previous run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

__all__ = [
    "redis_index_for_worker",
    "savepoint_session",
    "worker_id",
]


def worker_id() -> str:
    """``gw0``…``gwN`` under pytest-xdist, ``main`` otherwise."""
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


def redis_index_for_worker(offset: int = 0) -> int:
    """This worker's Redis database index.

    Mirrors the allocation the plugin exported, so a test that builds its own
    Redis client lands on the same index as the one the app is using rather than
    silently sharing index 0 with every other worker.
    """
    digits = "".join(c for c in worker_id() if c.isdigit())
    slot = int(digits) if digits else 0
    return (slot * 3 + offset) % 60


@asynccontextmanager
async def savepoint_session(
    engine: AsyncEngine, **session_kwargs: Any
) -> AsyncIterator[AsyncSession]:
    """A session whose every write is rolled back when the block exits.

    Implements SQLAlchemy's documented "join an external transaction" recipe:
    open a connection, begin a non-ORM transaction on it, and bind the session
    with ``join_transaction_mode="create_savepoint"``. The session may then
    ``commit()`` as much as it likes — each commit resolves to a SAVEPOINT
    release inside the outer transaction, which is discarded at the end.

    ``expire_on_commit=False`` because a test that commits and then reads an
    attribute off the same object should not trigger a refresh it did not ask
    for; the objects stay usable for assertions after the commit.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        **session_kwargs,
    )
    try:
        yield session
    finally:
        await session.close()
        # Discards everything the session did, including its commits.
        await transaction.rollback()
        await connection.close()
