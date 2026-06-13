"""Async engine runner for alembic env.py online mode (asyncpg, session-mode).

Every async-migration service hand-rolls the same ``create_async_engine`` +
``connection.run_sync`` boilerplate. This consolidates it so each env.py only
defines its ``do_run_migrations`` and calls ``run_async_migrations``.

The platform standardises on a single driver — asyncpg — for both runtime and
migrations (no psycopg2/psycopg3). This runner is the migration half of that.
"""

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.db.session import _to_asyncpg
from tr_shared.db.utils import to_session_mode_url


def run_async_migrations(
    url: str,
    do_run_migrations: Callable[[Any], None],
    *,
    connect_args: dict | None = None,
) -> None:
    """Sync entrypoint for an alembic env.py ``run_migrations_online()``.

    Builds a ``NullPool`` asyncpg engine in Supavisor session mode (port 5432,
    DDL-safe) and runs ``do_run_migrations(sync_connection)`` via
    ``connection.run_sync``. The caller's ``do_run_migrations`` owns
    ``context.configure`` + ``context.run_migrations``.

    Args:
        url: Raw ``DATABASE_URL`` (any Postgres scheme — normalised to asyncpg
            and to session mode here).
        do_run_migrations: Callback receiving the sync-proxy ``Connection``
            inside the greenlet. Typically calls
            ``bootstrap_schema_and_version_table`` then ``context.configure``.
        connect_args: asyncpg connect args. Defaults to
            ``{"statement_cache_size": 0}`` (PgBouncer/Supavisor-safe).

    Usage in env.py::

        from tr_shared.db import run_async_migrations

        def do_run_migrations(connection):
            ...  # bootstrap + context.configure + run_migrations

        def run_migrations_online():
            run_async_migrations(get_settings().database_url, do_run_migrations)
    """

    async def _run() -> None:
        engine = create_async_engine(
            _to_asyncpg(to_session_mode_url(url)),
            poolclass=NullPool,
            connect_args=connect_args or {"statement_cache_size": 0},
        )
        try:
            async with engine.connect() as connection:
                await connection.run_sync(do_run_migrations)
        finally:
            await engine.dispose()

    asyncio.run(_run())
