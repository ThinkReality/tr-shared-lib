import logging

import pytest
from sqlalchemy import text

from tr_shared.contracts.db_pool import DB_STATEMENT_TIMEOUT_SECONDS, StatementTimeoutProfile
from tr_shared.db import create_async_engine_factory
from tr_shared.db.session import IDLE_PING_SQL

pytestmark = pytest.mark.integration

_REQUEST_CAP = DB_STATEMENT_TIMEOUT_SECONDS[StatementTimeoutProfile.REQUEST]
_ONE_HOUR = 3600.0


def _single_connection_engine(dsn: str, idle_ping_after_seconds: float):
    return create_async_engine_factory(
        dsn,
        statement_timeout_seconds=_REQUEST_CAP,
        pool_size=1,
        max_overflow=0,
        idle_ping_after_seconds=idle_ping_after_seconds,
    )


async def test_a_connection_killed_while_idle_is_replaced(postgres_dsn, terminate_backend, caplog):
    engine = _single_connection_engine(postgres_dsn, idle_ping_after_seconds=0)
    try:
        async with engine.connect() as conn:
            pid = await conn.scalar(text("SELECT pg_backend_pid()"))
        await terminate_backend(pid)
        with caplog.at_level(logging.WARNING, logger="tr_shared.db.session"):
            async with engine.connect() as conn:
                assert await conn.scalar(text("SELECT 1")) == 1
                assert await conn.scalar(text("SELECT pg_backend_pid()")) != pid
    finally:
        await engine.dispose()
    [record] = [r for r in caplog.records if r.getMessage() == "db_stale_connection_replaced"]
    assert record.error_type
    assert record.idle_seconds >= 0


async def _activity_of(pid: int, dsn: str):
    observer = _single_connection_engine(dsn, idle_ping_after_seconds=_ONE_HOUR)
    try:
        async with observer.connect() as conn:
            row = await conn.execute(
                text("SELECT state, query FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
            )
            return row.one()
    finally:
        await observer.dispose()


async def test_an_idle_connection_is_validated_by_one_statement_outside_a_transaction(
    postgres_dsn,
):
    engine = _single_connection_engine(postgres_dsn, idle_ping_after_seconds=0)
    try:
        async with engine.connect() as conn:
            pid = await conn.scalar(text("SELECT pg_backend_pid()"))
        async with engine.connect():
            activity = await _activity_of(pid, postgres_dsn)
    finally:
        await engine.dispose()
    assert (activity.state, activity.query) == ("idle", IDLE_PING_SQL)


async def test_a_recently_used_connection_is_not_pinged(postgres_dsn):
    engine = _single_connection_engine(postgres_dsn, idle_ping_after_seconds=_ONE_HOUR)
    try:
        async with engine.connect() as conn:
            pid = await conn.scalar(text("SELECT pg_backend_pid()"))
        async with engine.connect():
            activity = await _activity_of(pid, postgres_dsn)
    finally:
        await engine.dispose()
    assert activity.query != IDLE_PING_SQL
