"""ORM flushes of ``BaseModel`` rows must batch into one multi-row INSERT.

SQLAlchemy's insertmanyvalues has to correlate ``RETURNING`` rows back to the objects
it is populating. A server-generated UUID primary key gives it nothing to correlate
on, so the unit of work "gracefully degrades" to one INSERT per row — on a pooler one
region away that is two round trips per row, fleet-wide, for every ``add_all()``.
A client-side default on the key is its own sentinel and restores batching.

Rows here are homogeneous on purpose: the flush groups objects by the set of
attributes each one carries, so heterogeneous rows still split into one INSERT per
group. That is a separate property and not what this module asserts.
"""

from __future__ import annotations

import subprocess
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.db.base import BaseModel

pytestmark = pytest.mark.integration

_CONTAINER = "tr-test-insert-batching-pg"
_IMAGE = "postgres:16-alpine"


class _Row(BaseModel):
    __tablename__ = "insert_batching_probe"


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
async def engine(postgres_dsn: str):
    engine = create_async_engine(postgres_dsn, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(_Row.__table__.create)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(_Row.__table__.drop)
        await engine.dispose()


@requires_docker
@pytest.mark.asyncio
async def test_add_all_flushes_in_one_insert(engine) -> None:
    tenant_id = uuid.uuid4()
    rows = [_Row(tenant_id=tenant_id) for _ in range(3)]
    assert all(row.id is None for row in rows), "id must stay unset until flush"

    inserts: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT"):
            inserts.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        async with AsyncSession(engine) as session:
            session.add_all(rows)
            await session.flush()
            ids = {row.id for row in rows}
            assert len(ids) == 3 and all(isinstance(i, uuid.UUID) for i in ids)
            persisted = await session.scalar(
                select(func.count()).select_from(_Row).where(_Row.tenant_id == tenant_id)
            )
            assert persisted == 3
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)

    assert len(inserts) == 1, f"expected one INSERT, issued {len(inserts)}: {inserts}"
