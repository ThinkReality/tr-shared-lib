import asyncio
import time

import pytest
import pytest_asyncio
from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.testing.stack import _adopt_or_create, _docker, _lock, _wait_ready

_CONTAINER = "tr-test-shared-lib-pg"
_IMAGE = "postgres:16-alpine"
_TERMINATE_POLLS = 50
_TERMINATE_POLL_SECONDS = 0.1
_SYNC_DRIVERS = ["postgresql+psycopg2", "postgresql+psycopg"]


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    client = _docker()
    with _lock(_CONTAINER):
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
    return f"postgresql+asyncpg://postgres:test@127.0.0.1:{port}/postgres"


@pytest_asyncio.fixture
async def terminate_backend(postgres_dsn: str):
    killer = create_async_engine(postgres_dsn, poolclass=NullPool, isolation_level="AUTOCOMMIT")

    async def _terminate(pid: int) -> None:
        async with killer.connect() as conn:
            await conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            for _ in range(_TERMINATE_POLLS):
                alive = await conn.scalar(
                    text("SELECT count(*) FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
                )
                if not alive:
                    return
                await asyncio.sleep(_TERMINATE_POLL_SECONDS)
        raise AssertionError(f"backend {pid} outlived pg_terminate_backend")

    yield _terminate
    await killer.dispose()


@pytest.fixture(params=_SYNC_DRIVERS)
def sync_driver(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def sync_dsn(sync_driver: str, postgres_dsn: str) -> URL:
    return make_url(postgres_dsn).set(drivername=sync_driver)


@pytest.fixture
def sync_admin(sync_dsn: URL):
    admin = create_engine(sync_dsn, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    yield admin
    admin.dispose()


@pytest.fixture
def terminate_backend_sync(sync_admin: Engine):
    def _terminate(pid: int) -> None:
        with sync_admin.connect() as conn:
            conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            for _ in range(_TERMINATE_POLLS):
                alive = conn.scalar(
                    text("SELECT count(*) FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
                )
                if not alive:
                    return
                time.sleep(_TERMINATE_POLL_SECONDS)
        raise AssertionError(f"backend {pid} outlived pg_terminate_backend")

    return _terminate
