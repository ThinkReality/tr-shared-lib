import logging

import pytest
from sqlalchemy import text

from tr_shared.contracts.db_pool import DB_STATEMENT_TIMEOUT_SECONDS, StatementTimeoutProfile
from tr_shared.db import create_async_engine_factory

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


async def test_a_recently_used_connection_is_not_pinged(postgres_dsn, monkeypatch):
    engine = _single_connection_engine(postgres_dsn, idle_ping_after_seconds=_ONE_HOUR)
    dialect = engine.sync_engine.dialect
    original = dialect.do_ping
    pings: list[object] = []

    def _spy(dbapi_connection):
        pings.append(dbapi_connection)
        return original(dbapi_connection)

    monkeypatch.setattr(dialect, "do_ping", _spy)
    try:
        for _ in range(2):
            async with engine.connect() as conn:
                await conn.scalar(text("SELECT 1"))
    finally:
        await engine.dispose()
    assert pings == []
