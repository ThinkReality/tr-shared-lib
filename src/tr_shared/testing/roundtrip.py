from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from tr_shared.testing.config import APP_ROLE, DATABASE_LAYOUT, admin_database_url

_PG_IDENTIFIER_MAX = 63


def _with_database(url: str, database: str) -> str:
    from sqlalchemy import make_url

    return make_url(url).set(database=database).render_as_string(hide_password=False)


async def _execute(url: str, statements: Sequence[str]) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@contextmanager
def roundtrip_database(database_url: str, suffix: str = "roundtrip") -> Iterator[str]:
    from sqlalchemy import make_url

    tail = f"_{suffix}"
    base = make_url(database_url).database or ""
    name = base[: _PG_IDENTIFIER_MAX - len(tail)] + tail
    admin = admin_database_url(database_url)
    server = _with_database(admin, "postgres")
    drop = f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'

    asyncio.run(_execute(server, [drop, f'CREATE DATABASE "{name}" OWNER {APP_ROLE}']))
    try:
        asyncio.run(_execute(_with_database(admin, name), DATABASE_LAYOUT))
        yield _with_database(database_url, name)
    finally:
        asyncio.run(_execute(server, [drop]))
