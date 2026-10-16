from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.testing import roundtrip_database

pytestmark = pytest.mark.integration


async def _scalar(url: str, sql: str) -> object:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return await conn.scalar(text(sql))
    finally:
        await engine.dispose()


async def _rows(url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text(sql))).all()]
    finally:
        await engine.dispose()


async def _execute(url: str, sql: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


async def _autocommit(url: str, sql: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


def _exists(server_url: str, name: str) -> bool:
    return bool(
        asyncio.run(
            _scalar(server_url, f"SELECT count(*) FROM pg_database WHERE datname = '{name}'")
        )
    )


def test_yields_the_callers_url_pointed_at_a_sibling_database(postgres_dsn: str) -> None:
    with roundtrip_database(postgres_dsn) as url:
        yielded = make_url(url)

    assert yielded.database == "postgres_roundtrip"
    assert yielded.set(database="postgres") == make_url(postgres_dsn)


def test_the_database_is_empty_owned_by_the_app_role_and_laid_out_like_staging(
    postgres_dsn: str,
) -> None:
    with roundtrip_database(postgres_dsn) as url:
        owner = asyncio.run(
            _scalar(
                url,
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()",
            )
        )
        extensions = dict(
            asyncio.run(
                _rows(
                    url,
                    "SELECT extname, extnamespace::regnamespace::text FROM pg_extension "
                    "WHERE extname <> 'plpgsql'",
                )
            )
        )
        tables = asyncio.run(
            _scalar(url, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        )

    assert owner == "postgres"
    assert extensions == {
        "pgcrypto": "extensions",
        "uuid-ossp": "extensions",
        "pg_trgm": "public",
        "supabase_vault": "vault",
    }
    assert tables == 0


def test_a_leftover_database_of_the_same_name_is_replaced(postgres_dsn: str) -> None:
    asyncio.run(_autocommit(postgres_dsn, 'DROP DATABASE IF EXISTS "postgres_leftover"'))
    asyncio.run(_autocommit(postgres_dsn, 'CREATE DATABASE "postgres_leftover"'))
    stale = (
        make_url(postgres_dsn)
        .set(database="postgres_leftover")
        .render_as_string(hide_password=False)
    )
    asyncio.run(_execute(stale, "CREATE TABLE public.stale (id int)"))

    with roundtrip_database(postgres_dsn, "leftover") as url:
        tables = asyncio.run(
            _scalar(url, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        )

    assert tables == 0


def test_the_database_is_dropped_on_exit_even_when_the_body_raises(postgres_dsn: str) -> None:
    with pytest.raises(RuntimeError), roundtrip_database(postgres_dsn, "raising") as url:
        name = make_url(url).database
        assert _exists(postgres_dsn, "postgres_raising")
        raise RuntimeError

    assert name == "postgres_raising"
    assert not _exists(postgres_dsn, "postgres_raising")


def test_a_long_name_is_cut_to_what_postgres_keeps(postgres_dsn: str) -> None:
    suffix = "s" * 60
    with roundtrip_database(postgres_dsn, suffix) as url:
        name = make_url(url).database
        current = asyncio.run(_scalar(url, "SELECT current_database()"))

    assert name is not None
    assert len(name) == 63
    assert name.endswith(suffix)
    assert current == name
