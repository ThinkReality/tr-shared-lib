"""Savepoint isolation against real Postgres.

The property under test is the one that is easy to assume and easy to get wrong:
a test may ``commit()``, see its own data, and still leave the database exactly
as it found it. Asserting that requires a real server — SAVEPOINT semantics are
precisely what an in-memory stand-in does not reproduce, which is why the
standard bans sqlite outright.
"""

from __future__ import annotations

import subprocess
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.testing.isolation import (
    redis_index_for_worker,
    savepoint_session,
    worker_id,
)

pytestmark = pytest.mark.integration

_CONTAINER = "tr-test-isolation-pg"
_IMAGE = "postgres:16-alpine"


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(not _docker_available(), reason="Docker is not reachable")


@pytest.fixture(scope="module")
def postgres_dsn() -> str:
    """A throwaway Postgres for this module, reusing the library's own provisioner."""
    from tr_shared.testing.stack import _adopt_or_create, _docker, _wait_ready

    client = _docker()
    container = _adopt_or_create(
        client,
        name=_CONTAINER,
        image=_IMAGE,
        container_port=5432,
        environment={
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "test",
            "POSTGRES_DB": "postgres",
        },
        command=None,
    )
    container.reload()
    port = int(container.ports["5432/tcp"][0]["HostPort"])
    _wait_ready(
        container,
        ["psql", "-U", "postgres", "-d", "postgres", "-tAc", "SELECT 1"],
        _CONTAINER,
    )
    yield f"postgresql+asyncpg://postgres:test@127.0.0.1:{port}/postgres"
    subprocess.run(["docker", "rm", "-f", _CONTAINER], capture_output=True)


@pytest_asyncio.fixture
async def db(postgres_dsn: str):
    """An engine plus a table private to this test.

    Yielded as a pair rather than stashed on the engine: AsyncEngine defines
    __slots__, so it accepts no ad-hoc attributes.
    """
    engine = create_async_engine(postgres_dsn, poolclass=NullPool)
    table = f"iso_{uuid.uuid4().hex[:8]}"
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table} (id int primary key)"))
    try:
        yield engine, table
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        await engine.dispose()


async def _count(engine, table: str) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text(f"SELECT count(*) FROM {table}"))
        return int(result.scalar_one())


@requires_docker
class TestSavepointRollback:
    @pytest.mark.asyncio
    async def test_writes_are_visible_inside_the_block(self, db) -> None:
        engine, table = db
        async with savepoint_session(engine) as session:
            await session.execute(text(f"INSERT INTO {table} VALUES (1)"))
            result = await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert result.scalar_one() == 1

    @pytest.mark.asyncio
    async def test_uncommitted_writes_do_not_survive(self, db) -> None:
        engine, table = db
        async with savepoint_session(engine) as session:
            await session.execute(text(f"INSERT INTO {table} VALUES (2)"))
        assert await _count(engine, table) == 0

    @pytest.mark.asyncio
    async def test_COMMITTED_writes_do_not_survive_either(self, db) -> None:
        """The whole point. A committed write inside the block is still discarded.

        Without join_transaction_mode="create_savepoint" the session's commit
        would resolve against the outer transaction and the row would persist,
        leaking into every later test.
        """
        engine, table = db
        async with savepoint_session(engine) as session:
            await session.execute(text(f"INSERT INTO {table} VALUES (3)"))
            await session.commit()
            result = await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert result.scalar_one() == 1

        assert await _count(engine, table) == 0

    @pytest.mark.asyncio
    async def test_a_session_rollback_does_not_break_the_outer_transaction(self, db) -> None:
        engine, table = db
        async with savepoint_session(engine) as session:
            await session.execute(text(f"INSERT INTO {table} VALUES (4)"))
            await session.rollback()
            # The outer transaction is still usable after the inner rollback.
            await session.execute(text(f"INSERT INTO {table} VALUES (5)"))
            await session.commit()

        assert await _count(engine, table) == 0

    @pytest.mark.asyncio
    async def test_consecutive_blocks_do_not_see_each_other(self, db) -> None:
        engine, table = db
        async with savepoint_session(engine) as first:
            await first.execute(text(f"INSERT INTO {table} VALUES (6)"))
            await first.commit()

        async with savepoint_session(engine) as second:
            result = await second.execute(text(f"SELECT count(*) FROM {table}"))
            assert result.scalar_one() == 0

    @pytest.mark.asyncio
    async def test_an_error_inside_the_block_still_rolls_back(self, db) -> None:
        engine, table = db
        with pytest.raises(ValueError):
            async with savepoint_session(engine) as session:
                await session.execute(text(f"INSERT INTO {table} VALUES (7)"))
                await session.commit()
                raise ValueError("boom")

        assert await _count(engine, table) == 0


class TestWorkerAllocation:
    def test_worker_id_defaults_to_main(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
        assert worker_id() == "main"

    def test_each_worker_gets_a_distinct_index_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = []
        for slot in range(5):
            monkeypatch.setenv("PYTEST_XDIST_WORKER", f"gw{slot}")
            seen.append(redis_index_for_worker())
        # Three consecutive indexes per worker (cache, broker, results) must not
        # overlap between workers.
        assert seen == [0, 3, 6, 9, 12]
        assert len(set(seen)) == len(seen)

    def test_offsets_stay_inside_the_worker_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
        assert [redis_index_for_worker(o) for o in range(3)] == [6, 7, 8]
