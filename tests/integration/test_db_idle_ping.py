import asyncio
import logging

import pytest
from sqlalchemy import make_url, text

from tr_shared.contracts.db_pool import (
    DB_IDLE_PING_TIMEOUT_SECONDS,
    DB_STATEMENT_TIMEOUT_SECONDS,
    StatementTimeoutProfile,
)
from tr_shared.db import create_async_engine_factory
from tr_shared.db.session import IDLE_PING_SQL

pytestmark = pytest.mark.integration

_REQUEST_CAP = DB_STATEMENT_TIMEOUT_SECONDS[StatementTimeoutProfile.REQUEST]
_ONE_HOUR = 3600.0
_SLACK_SECONDS = 2


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


class _FreezableLink:
    def __init__(self, host: str, port: int):
        self._target = (host, port)
        self._flowing: list[asyncio.Event] = []
        self._pipes: list[asyncio.Task] = []
        self._writers: list[asyncio.StreamWriter] = []

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    def freeze_open_connections(self) -> None:
        for flowing in self._flowing:
            flowing.clear()

    def close(self) -> None:
        for pipe in self._pipes:
            pipe.cancel()
        for writer in self._writers:
            writer.close()
        self._server.close()

    async def _accept(self, reader, writer) -> None:
        upstream_reader, upstream_writer = await asyncio.open_connection(*self._target)
        flowing = asyncio.Event()
        flowing.set()
        self._flowing.append(flowing)
        self._writers += [writer, upstream_writer]
        self._pipes += [
            asyncio.create_task(self._pipe(reader, upstream_writer, flowing)),
            asyncio.create_task(self._pipe(upstream_reader, writer, flowing)),
        ]

    async def _pipe(self, reader, writer, flowing: asyncio.Event) -> None:
        while data := await reader.read(65536):
            await flowing.wait()
            writer.write(data)
            await writer.drain()
        writer.close()


async def _select_one(engine) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(text("SELECT 1"))


async def test_a_stalled_idle_connection_is_replaced_within_the_ping_budget(postgres_dsn):
    url = make_url(postgres_dsn)
    link = _FreezableLink(url.host, url.port)
    proxied_dsn = url.set(host="127.0.0.1", port=await link.start()).render_as_string(
        hide_password=False
    )
    engine = _single_connection_engine(proxied_dsn, idle_ping_after_seconds=0)
    try:
        await _select_one(engine)
        link.freeze_open_connections()
        checkout = asyncio.create_task(_select_one(engine))
        done, _ = await asyncio.wait(
            {checkout}, timeout=DB_IDLE_PING_TIMEOUT_SECONDS + _SLACK_SECONDS
        )
        while not checkout.done():
            checkout.cancel()
            await asyncio.wait({checkout}, timeout=0.1)
    finally:
        link.close()
        await engine.dispose()
    assert done, "a stalled idle connection held the checkout past the ping budget"
    assert checkout.result() == 1
