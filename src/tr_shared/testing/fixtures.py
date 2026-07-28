"""Ready-made fixtures. Opt in from ``tests/conftest.py``::

    pytest_plugins = ["tr_shared.testing.fixtures"]

``pytest_plugins`` is only legal in the rootdir conftest — pytest hard-errors on
it anywhere else — which is also where a service should be making this choice.

These are *not* loaded by the entry-point plugin. The plugin's job is to resolve
the lane and the environment for every opted-in service; fixtures are a menu, and
a service with its own well-shaped ``db_session`` should keep it.

Names are prefixed ``tr_`` so adopting this file cannot shadow a fixture a
service already has. Alias locally if the short name is wanted::

    @pytest.fixture
    def db_session(tr_session):
        return tr_session
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from tr_shared.testing.isolation import (
    redis_index_for_worker,
    savepoint_session,
    worker_id,
)
from tr_shared.testing.lanes import POISON_DATABASE_URL

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture(scope="session")
def tr_worker_id() -> str:
    return worker_id()


@pytest.fixture(scope="session")
def tr_database_url() -> str:
    """The DSN the plugin resolved for this worker.

    Fails loudly rather than skipping if the run is in the unit lane: a unit test
    asking for a database is a design error in the test, not a reason to grant it
    one.
    """
    url = os.environ.get("DATABASE_URL")
    if not url or url == POISON_DATABASE_URL:
        raise RuntimeError(
            "This test asked for a database while running in the UNIT lane, which "
            "has none. Move it under tests/integration/ (the path decides the "
            "lane), or drop the database dependency."
        )
    return url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def tr_engine(tr_database_url: str) -> AsyncIterator[AsyncEngine]:
    """One engine per worker, against that worker's own cloned database.

    ``NullPool`` because the session-scoped event loop and the per-test sessions
    do not share a lifetime; a pooled connection outliving its loop is the classic
    "attached to a different loop" failure.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(tr_database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def tr_session(tr_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose writes — including committed ones — are rolled back."""
    async with savepoint_session(tr_engine) as session:
        yield session


@pytest.fixture(scope="session")
def tr_redis_index() -> int:
    return redis_index_for_worker()


@pytest.fixture
def tr_redis(tr_redis_index: int) -> Iterator[Any]:
    """A Redis client on this worker's index, flushed before and after.

    Flushing that index is safe precisely because it belongs to this worker
    alone. Doing the same on a shared index is how one worker's cleanup empties
    another's cache mid-assertion.
    """
    import redis

    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL is unset; this test needs the integration lane.")

    client = redis.Redis.from_url(url, decode_responses=True)
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()
