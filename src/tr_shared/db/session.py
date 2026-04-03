"""
Shared async database session factory.

Extracted from tr-lead-management (PgBouncer-safe, NullPool) and
crm-backend (simpler NullPool pattern). Provides factory functions
so each service controls its own engine/session lifecycle.

Usage::

    from tr_shared.db import create_async_engine_factory, create_session_factory, get_db

    engine = create_async_engine_factory(settings.DATABASE_URL)
    AsyncSessionLocal = create_session_factory(engine)

    # FastAPI dependency
    app.dependency_overrides[get_db] = lambda: _get_session(AsyncSessionLocal)
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def _to_asyncpg(url: str) -> str:
    """Normalise a Postgres URL to the asyncpg dialect."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# PgBouncer-safe connect args (disable prepared-statement caching)
PGBOUNCER_CONNECT_ARGS: dict = {
    "statement_cache_size": 0,
    "prepared_statement_cache_size": 0,
    "prepared_statement_name_func": lambda: "",
    "command_timeout": 60,
    "server_settings": {"jit": "off"},
}


def create_async_engine_factory(
    database_url: str,
    echo: bool = False,
    pool_class=NullPool,
    connect_args: dict | None = None,
    **engine_kwargs,
) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine.

    Args:
        database_url: Postgres connection string (any dialect prefix accepted).
        echo: Echo SQL statements.
        pool_class: Pool implementation. NullPool for Supabase/PgBouncer.
        connect_args: Extra asyncpg connect args. Defaults to PgBouncer-safe set.
        **engine_kwargs: Additional kwargs forwarded to ``create_async_engine``
            (e.g. ``pool_size``, ``max_overflow``, ``pool_timeout``,
            ``pool_recycle``, ``echo_pool``).  NullPool silently ignores
            pool-sizing parameters.
    """
    return create_async_engine(
        _to_asyncpg(database_url),
        echo=echo,
        poolclass=pool_class,
        pool_pre_ping=True,
        connect_args=connect_args or PGBOUNCER_CONNECT_ARGS,
        **engine_kwargs,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a transactional session.

    Each service wires this up by partially applying its own session factory::

        from functools import partial
        app.dependency_overrides[get_db] = partial(get_db, session_factory=AsyncSessionLocal)
    """
    if session_factory is None:
        raise RuntimeError(
            "get_db() called without a session_factory — "
            "wire it up via dependency_overrides in main.py"
        )
    async with session_factory() as session, session.begin():
        yield session
