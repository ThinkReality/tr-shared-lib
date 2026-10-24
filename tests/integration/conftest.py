import asyncio
import hashlib
import time

import pytest
import pytest_asyncio
from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.testing.config import (
    _DEFAULT_POSTGRES_IMAGE,
    _DEFAULT_REDIS_IMAGE,
    APP_ROLE,
    PASSWORD,
)
from tr_shared.testing.isolation import worker_id
from tr_shared.testing.stack import (
    _POSTGRES_ENVIRONMENT,
    _POSTGRES_READY_PROBE,
    _REDIS_COMMAND,
    _REDIS_READY_PROBE,
    _adopt_or_create,
    _docker,
    _ensure_container,
    _lock,
    _wait_ready,
    redis_triple,
)

_CONTAINER = (
    f"tr-test-shared-lib-pg-{hashlib.sha256(_DEFAULT_POSTGRES_IMAGE.encode()).hexdigest()[:10]}"
)
_REDIS_CONTAINER = (
    f"tr-test-shared-lib-redis-{hashlib.sha256(_DEFAULT_REDIS_IMAGE.encode()).hexdigest()[:10]}"
)
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
            image=_DEFAULT_POSTGRES_IMAGE,
            container_port=5432,
            environment=_POSTGRES_ENVIRONMENT,
            command=None,
        )
        container.reload()
        port = int(container.ports["5432/tcp"][0]["HostPort"])
        _wait_ready(container, _POSTGRES_READY_PROBE, _CONTAINER)
    return f"postgresql+asyncpg://{APP_ROLE}:{PASSWORD}@127.0.0.1:{port}/postgres"


@pytest.fixture(scope="session")
def redis_url() -> str:
    client = _docker()
    with _lock(_REDIS_CONTAINER):
        port = _ensure_container(
            client,
            name=_REDIS_CONTAINER,
            image=_DEFAULT_REDIS_IMAGE,
            container_port=6379,
            environment={},
            command=_REDIS_COMMAND,
            ready_probe=_REDIS_READY_PROBE,
        )
    return redis_triple(f"redis://127.0.0.1:{port}", worker_id())[0]


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
