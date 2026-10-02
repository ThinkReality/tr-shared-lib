import asyncio
import logging
import time
import uuid

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import make_url, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.contracts import UNAVAILABLE_RETRY_AFTER_SECONDS, DatabaseOutageCode
from tr_shared.contracts.db_pool import (
    DB_CONNECT_TIMEOUT_SECONDS,
    DB_STATEMENT_TIMEOUT_SECONDS,
    StatementTimeoutProfile,
)
from tr_shared.db import (
    DatabaseTimeoutError,
    DatabaseUnavailableError,
    create_async_engine_factory,
    run_async_migrations,
)
from tr_shared.middleware import register_exception_handlers

pytestmark = pytest.mark.integration

_REQUEST_CAP = DB_STATEMENT_TIMEOUT_SECONDS[StatementTimeoutProfile.REQUEST]
_SHORT_CAP = 1.0
_SLACK_SECONDS = 2


def _raise_sqlstate(sqlstate: str) -> str:
    return f"DO $$ BEGIN RAISE EXCEPTION 'relayed' USING ERRCODE = '{sqlstate}'; END $$"


def _engine(dsn: str, statement_timeout_seconds: float = _REQUEST_CAP):
    return create_async_engine_factory(dsn, statement_timeout_seconds=statement_timeout_seconds)


async def _connect_once(engine) -> None:
    try:
        async with engine.connect():
            pass
    finally:
        await engine.dispose()


async def test_a_refused_connect_is_unavailable():
    with pytest.raises(DatabaseUnavailableError) as caught:
        await _connect_once(_engine("postgresql://u:p@127.0.0.1:1/db"))
    assert caught.value.code is DatabaseOutageCode.CONNECT_FAILED
    assert isinstance(caught.value.__cause__, OSError)


async def test_a_role_over_its_connection_limit_is_unavailable(postgres_dsn):
    role = f"tr_capped_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(postgres_dsn, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'capped' CONNECTION LIMIT 0"))
    capped = make_url(postgres_dsn).set(username=role, password="capped")
    try:
        with pytest.raises(DatabaseUnavailableError) as caught:
            await _connect_once(_engine(capped.render_as_string(hide_password=False)))
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f"DROP ROLE {role}"))
        await admin.dispose()
    assert caught.value.code is DatabaseOutageCode.CONNECT_FAILED
    assert isinstance(caught.value.__cause__, asyncpg.exceptions.TooManyConnectionsError)


async def test_a_wrong_password_is_not_reported_as_an_outage(postgres_dsn):
    wrong = make_url(postgres_dsn).set(password="wrong")
    with pytest.raises(asyncpg.exceptions.InvalidPasswordError):
        await _connect_once(_engine(wrong.render_as_string(hide_password=False)))


async def test_a_statement_over_its_cap_is_typed_and_logged(postgres_dsn, caplog):
    engine = _engine(postgres_dsn, statement_timeout_seconds=_SHORT_CAP)
    try:
        with caplog.at_level(logging.WARNING, logger="tr_shared.db.session"):
            with pytest.raises(DatabaseTimeoutError):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT pg_sleep(:s)"), {"s": _SHORT_CAP * 3})
    finally:
        await engine.dispose()
    [record] = [r for r in caplog.records if r.getMessage() == "db_statement_timeout"]
    assert "pg_sleep" in record.statement
    assert record.statement_timeout_seconds == _SHORT_CAP


async def test_a_connection_lost_mid_request_is_503_even_when_the_route_swallows_sqlalchemy_errors(
    postgres_dsn, terminate_backend
):
    engine = _engine(postgres_dsn)
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/permissions")
    async def permissions() -> list[str]:
        async with engine.connect() as conn:
            pid = await conn.scalar(text("SELECT pg_backend_pid()"))
            await terminate_backend(pid)
            try:
                await conn.execute(text("SELECT 1"))
            except SQLAlchemyError:
                return []
        return ["granted"]

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/permissions")
    finally:
        await engine.dispose()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == DatabaseOutageCode.CONNECTION_LOST
    assert response.headers["retry-after"] == str(UNAVAILABLE_RETRY_AFTER_SECONDS)


async def test_a_cancelled_query_stays_cancelled(postgres_dsn):
    engine = _engine(postgres_dsn)

    async def _sleep() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_sleep(:s)"), {"s": _REQUEST_CAP})

    task = asyncio.create_task(_sleep())
    await asyncio.sleep(_SHORT_CAP)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await engine.dispose()


@pytest.mark.parametrize("sqlstate", ["08006", "57P01", "57P03"])
async def test_a_relayed_backend_outage_is_connection_lost(postgres_dsn, sqlstate):
    engine = _engine(postgres_dsn)
    try:
        with pytest.raises(DatabaseUnavailableError) as caught:
            async with engine.connect() as conn:
                await conn.execute(text(_raise_sqlstate(sqlstate)))
    finally:
        await engine.dispose()
    assert caught.value.code is DatabaseOutageCode.CONNECTION_LOST


async def test_an_error_on_a_live_connection_is_not_an_outage(postgres_dsn):
    engine = _engine(postgres_dsn)
    try:
        with pytest.raises(DBAPIError):
            async with engine.connect() as conn:
                await conn.execute(text(_raise_sqlstate("53100")))
    finally:
        await engine.dispose()


async def test_pre_ping_still_replaces_a_dead_connection(postgres_dsn, terminate_backend):
    engine = create_async_engine_factory(
        postgres_dsn,
        statement_timeout_seconds=_REQUEST_CAP,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as conn:
            pid = await conn.scalar(text("SELECT pg_backend_pid()"))
        await terminate_backend(pid)
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT pg_backend_pid()")) != pid
    finally:
        await engine.dispose()


def _one_slot_engine(dsn: str, pool_timeout: float):
    return create_async_engine_factory(
        dsn,
        statement_timeout_seconds=_REQUEST_CAP,
        pool_size=1,
        max_overflow=0,
        pool_timeout=pool_timeout,
    )


async def test_an_exhausted_pool_is_503_even_when_the_route_swallows_sqlalchemy_errors(
    postgres_dsn,
):
    engine = _one_slot_engine(postgres_dsn, pool_timeout=_SHORT_CAP)
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/permissions")
    async def permissions() -> list[str]:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return []
        return ["granted"]

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async with engine.connect() as held:
                await held.execute(text("SELECT 1"))
                exhausted = await client.get("/permissions")
            recovered = await client.get("/permissions")
    finally:
        await engine.dispose()
    assert exhausted.status_code == 503
    assert exhausted.json()["error"]["code"] == DatabaseOutageCode.POOL_EXHAUSTED
    assert exhausted.headers["retry-after"] == str(UNAVAILABLE_RETRY_AFTER_SECONDS)
    assert recovered.status_code == 200
    assert recovered.json() == ["granted"]


async def test_a_cancelled_pool_wait_stays_cancelled(postgres_dsn):
    engine = _one_slot_engine(postgres_dsn, pool_timeout=_REQUEST_CAP)

    async def _wait_for_a_slot() -> None:
        async with engine.connect():
            pass

    try:
        async with engine.connect() as held:
            await held.execute(text("SELECT 1"))
            waiter = asyncio.create_task(_wait_for_a_slot())
            await asyncio.sleep(_SHORT_CAP)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
    finally:
        await engine.dispose()


_BLACKHOLE_DSN = "postgresql://u:p@10.255.255.1:5432/db"


async def test_a_blackholed_connect_gives_up_at_the_contract_budget():
    started = time.monotonic()
    with pytest.raises(DatabaseUnavailableError) as caught:
        await _connect_once(_engine(_BLACKHOLE_DSN))
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert time.monotonic() - started < DB_CONNECT_TIMEOUT_SECONDS + _SLACK_SECONDS


def test_the_migration_runner_gives_up_at_the_contract_budget():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_async_migrations(_BLACKHOLE_DSN, lambda connection: None)
    assert time.monotonic() - started < DB_CONNECT_TIMEOUT_SECONDS + _SLACK_SECONDS
