"""
Shared async database session factory.

Provides factory functions so each service controls its own engine/session
lifecycle while getting PgBouncer/Supavisor-safe connect args and a client-side
connection pool sized for the Supavisor client cap automatically.

Usage::

    from tr_shared.db import create_async_engine_factory, create_session_factory, get_db

    engine = create_async_engine_factory(
        settings.DATABASE_URL,
        service_name="lead",
        schema="lead",
    )
    AsyncSessionLocal = create_session_factory(engine)

    # FastAPI dependency
    app.dependency_overrides[get_db] = lambda: _get_session(AsyncSessionLocal)
"""

import copy
import weakref
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, QueuePool


def _to_asyncpg(url: str) -> str:
    """Normalise a Postgres URL to the asyncpg dialect."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# Client-side pool policy. A long-lived container keeps a few warm connections instead of
# paying TCP + TLS + SCRAM plus asyncpg's type introspection on every request (~6 round
# trips before the first statement).
#
# pool_size is what a process holds at rest and is what the Supavisor client cap (200 on
# the smallest compute) has to absorb fleet-wide: every uvicorn worker and every Celery
# prefork child owns a pool, ~52 engines × 2 ≈ 104. max_overflow is burst room; overflow
# connections are closed on return, so they cost a client slot only while a burst lasts.
# 8 gives one API process 10 concurrent checkouts — two workers absorb the board's 20
# parallel page fetches without queueing; the 11th waits up to pool_timeout. A prefork
# child runs one task at a time and never approaches the ceiling.
#
# Recycle at 300 s bounds a connection's idle time from above (idle ≤ age): measured alive
# after 310 s idle on the pooler, and under the ~350 s idle timeout of cloud NATs — that
# is what stands in for pre-ping, which under asyncpg in pgbouncer mode is
# BEGIN + fetchrow(";") + ROLLBACK on every checkout: four round trips, most of the gain.
DEFAULT_POOL_SIZE = 2
DEFAULT_MAX_OVERFLOW = 8
DEFAULT_POOL_KWARGS: dict = {
    "pool_size": DEFAULT_POOL_SIZE,
    "max_overflow": DEFAULT_MAX_OVERFLOW,
    "pool_timeout": 10,
    "pool_recycle": 300,
}

# Every engine the factory has built, so a forked Celery child can drop the connections it
# inherited (see dispose_engines_after_fork). Weak: an engine a test discards must not be
# kept alive by this registry.
_engines: weakref.WeakSet[AsyncEngine] = weakref.WeakSet()

# PgBouncer-safe connect args (disable prepared-statement caching)
PGBOUNCER_CONNECT_ARGS: dict = {
    "statement_cache_size": 0,
    "prepared_statement_cache_size": 0,
    "prepared_statement_name_func": lambda: "",
    "command_timeout": 60,
    "server_settings": {"jit": "off"},
}


def _build_connect_args(
    service_name: str,
    schema: str,
    overrides: dict | None,
) -> dict:
    """Build connect_args by merging overrides on top of PGBOUNCER_CONNECT_ARGS.

    Merge rules:
    - Starts with a deep copy of PGBOUNCER_CONNECT_ARGS (never mutates the original).
    - ``service_name`` injects ``server_settings.application_name``.
    - ``schema`` injects ``server_settings.search_path`` as ``"{schema},public"``.
    - ``overrides`` top-level keys overwrite defaults.
    - ``overrides["server_settings"]`` is **merged** into the existing sub-dict
      so callers can add keys (e.g. ``plan_cache_mode``) without losing
      ``jit``, ``application_name``, or ``search_path``.
    """
    args = copy.deepcopy(PGBOUNCER_CONNECT_ARGS)

    if service_name:
        args["server_settings"]["application_name"] = service_name
    if schema:
        args["server_settings"]["search_path"] = f"{schema},public"

    if overrides:
        for key, value in overrides.items():
            if key == "server_settings" and isinstance(value, dict):
                args["server_settings"].update(value)
            else:
                args[key] = value

    return args


def create_async_engine_factory(
    database_url: str,
    *,
    service_name: str = "",
    schema: str = "",
    echo: bool = False,
    pool_class: type = AsyncAdaptedQueuePool,
    connect_args: dict | None = None,
    **engine_kwargs,
) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine.

    Args:
        database_url: Postgres connection string (any dialect prefix accepted).
        service_name: Injected as ``application_name`` in ``server_settings``.
            Shows up in ``pg_stat_activity`` to identify the owning service.
        schema: Injected as ``search_path`` (``"{schema},public"``) in
            ``server_settings`` for connection-level schema isolation.
        echo: Echo SQL statements.
        pool_class: Pool implementation. The default keeps ``DEFAULT_POOL_KWARGS``
            warm connections (see the note on that constant); pass ``NullPool``
            for one-shot processes such as the migration runner.
        connect_args: Extra asyncpg connect args **merged** on top of the
            PgBouncer-safe defaults.  The ``server_settings`` sub-dict is
            merged (not replaced), so callers can add keys without losing
            ``jit``, ``application_name``, or ``search_path``.
        **engine_kwargs: Additional kwargs forwarded to ``create_async_engine``
            (e.g. ``pool_size``, ``max_overflow``, ``pool_timeout``,
            ``pool_recycle``, ``echo_pool``), overriding ``DEFAULT_POOL_KWARGS``
            key by key. Sizing is only applied to queue pools — SQLAlchemy
            rejects it on ``NullPool``.

    Test lanes: a pooled asyncpg connection is bound to the event loop that opened
    it, so a suite that reuses the service's engine across tests needs one loop for
    the whole session (``asyncio_default_test_loop_scope = "session"`` and the
    fixture equivalent in ``pytest.ini_options``) — not a NullPool branch in
    production code.
    """
    if issubclass(pool_class, QueuePool):
        engine_kwargs = {**DEFAULT_POOL_KWARGS, **engine_kwargs}
    engine = create_async_engine(
        _to_asyncpg(database_url),
        echo=echo,
        poolclass=pool_class,
        connect_args=_build_connect_args(service_name, schema, connect_args),
        **engine_kwargs,
    )
    _engines.add(engine)
    return engine


def dispose_engines_after_fork() -> None:
    """Drop, without closing, every pooled connection this process inherited from its
    parent. SQLAlchemy's prescription for ``os.fork()``: a socket checked in by the parent
    and reused from the child is silent cross-process corruption; ``close=False`` leaves
    the parent's copies untouched. ``create_celery_app`` wires this to
    ``worker_process_init`` so every prefork child starts with an empty pool.
    """
    for engine in list(_engines):
        engine.sync_engine.dispose(close=False)


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
