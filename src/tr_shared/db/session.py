"""
Shared async database session factory.

Provides factory functions so each service controls its own engine/session
lifecycle while getting PgBouncer/Supavisor-safe connect args and a client-side
connection pool sized for the Supavisor client cap automatically.

Usage::

    from tr_shared.db import create_async_engine_factory, create_session_factory, get_db

    engine = create_async_engine_factory(
        settings.DATABASE_URL,
        statement_timeout_seconds=settings.database_statement_timeout_seconds,
        service_name="lead",
        schema="lead",
    )
    AsyncSessionLocal = create_session_factory(engine)

    # FastAPI dependency
    app.dependency_overrides[get_db] = lambda: _get_session(AsyncSessionLocal)
"""

import copy
import logging
import time
import weakref
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, Dialect, Engine
from sqlalchemy.engine.base import ExceptionContextImpl
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.exc import InvalidatePoolError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import (
    AsyncAdaptedQueuePool,
    ConnectionPoolEntry,
    NullPool,
    PoolProxiedConnection,
    QueuePool,
)

from tr_shared.contracts.availability import DatabaseOutageCode
from tr_shared.contracts.db_pool import (
    DB_CONNECT_TIMEOUT_SECONDS,
    DB_IDLE_PING_AFTER_SECONDS,
    DEFAULT_POOL_KWARGS,
)
from tr_shared.db.errors import DatabaseTimeoutError, DatabaseUnavailableError


def _to_asyncpg(url: str) -> str:
    """Normalise a Postgres URL to the asyncpg dialect."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# Every engine the factory has built, so a forked Celery child can drop the connections it
# inherited (see dispose_engines_after_fork). Weak: an engine a test discards must not be
# kept alive by this registry.
_engines: weakref.WeakSet[AsyncEngine] = weakref.WeakSet()

# PgBouncer-safe connect args (disable prepared-statement caching)
PGBOUNCER_CONNECT_ARGS: dict = {
    "statement_cache_size": 0,
    "prepared_statement_cache_size": 0,
    "prepared_statement_name_func": lambda: "",
    "timeout": DB_CONNECT_TIMEOUT_SECONDS,
    "server_settings": {"jit": "off"},
}

_STATEMENT_TIMEOUT_SETTING = "statement_timeout"


def _sets_statement_timeout(server_settings: dict) -> bool:
    lowered = {str(key).lower(): str(value) for key, value in server_settings.items()}
    options = lowered.get("options", "").lower().replace("-", "_")
    return _STATEMENT_TIMEOUT_SETTING in lowered or _STATEMENT_TIMEOUT_SETTING in options


def _build_connect_args(
    service_name: str,
    schema: str,
    overrides: dict | None,
    *,
    statement_timeout_seconds: float,
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
    - ``overrides`` may not set the statement cap (``command_timeout``, a
      ``server_settings`` ``statement_timeout`` key in any case, or
      ``statement_timeout`` inside ``server_settings.options``); it comes only from
      ``statement_timeout_seconds``.
    """
    overrides = overrides or {}
    if "command_timeout" in overrides or _sets_statement_timeout(
        overrides.get("server_settings", {})
    ):
        raise ValueError("the statement cap comes from statement_timeout_seconds, not connect_args")
    args = copy.deepcopy(PGBOUNCER_CONNECT_ARGS)
    args["command_timeout"] = statement_timeout_seconds

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


logger = logging.getLogger(__name__)

_QUERY_CANCELED_SQLSTATE = "57014"
_CONNECT_FAILED_SQLSTATE_PREFIXES = ("08", "53", "57")
_CONNECTION_LOST_SQLSTATE_PREFIXES = ("08", "57P")


def _is_unavailable(exc: Exception, sqlstate_prefixes: tuple[str, ...]) -> bool:
    sqlstate = getattr(exc, "sqlstate", None) or ""
    return isinstance(exc, OSError) or sqlstate.startswith(sqlstate_prefixes)


def _install_error_translation(
    engine: AsyncEngine, *, service_name: str, statement_timeout_seconds: float
) -> None:
    sync_engine = engine.sync_engine

    def _connect(
        dialect: Dialect,
        connection_record: ConnectionPoolEntry,
        cargs: list[Any],
        cparams: dict[str, Any],
    ) -> DBAPIConnection:
        try:
            return dialect.connect(*cargs, **cparams)
        except Exception as exc:
            if _is_unavailable(exc, _CONNECT_FAILED_SQLSTATE_PREFIXES):
                raise DatabaseUnavailableError(
                    f"could not connect: {type(exc).__name__}",
                    code=DatabaseOutageCode.CONNECT_FAILED,
                ) from exc
            raise

    def _translate(context: ExceptionContextImpl) -> None:
        original = context.original_exception
        if context.is_pre_ping or not isinstance(original, Exception):
            return
        client_timed_out = isinstance(original, TimeoutError)
        if client_timed_out:
            context.is_disconnect = True
            context.invalidate_pool_on_disconnect = False
        if client_timed_out or getattr(original, "sqlstate", None) == _QUERY_CANCELED_SQLSTATE:
            logger.warning(
                "db_statement_timeout",
                extra={
                    "application_name": service_name,
                    "statement_timeout_seconds": statement_timeout_seconds,
                    "statement": context.statement,
                },
            )
            raise DatabaseTimeoutError("statement exceeded its time cap") from original
        if _is_unavailable(original, _CONNECTION_LOST_SQLSTATE_PREFIXES):
            context.is_disconnect = True
        if context.is_disconnect:
            raise DatabaseUnavailableError(
                f"connection lost: {type(original).__name__}",
                code=DatabaseOutageCode.CONNECTION_LOST,
            ) from original

    event.listen(sync_engine, "do_connect", _connect, insert=True)
    event.listen(sync_engine, "handle_error", _translate)


_CHECKED_IN_AT = "tr_checked_in_at"


def _install_idle_validation(
    engine: AsyncEngine, *, idle_ping_after_seconds: float, service_name: str
) -> None:
    sync_engine = engine.sync_engine

    def _stamp(dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry) -> None:
        connection_record.info[_CHECKED_IN_AT] = time.monotonic()

    def _validate(
        dbapi_connection: DBAPIConnection,
        connection_record: ConnectionPoolEntry,
        connection_proxy: PoolProxiedConnection,
    ) -> None:
        checked_in_at = connection_record.info.get(_CHECKED_IN_AT)
        if checked_in_at is None:
            return
        idle_seconds = time.monotonic() - checked_in_at
        if idle_seconds < idle_ping_after_seconds:
            return
        try:
            sync_engine.dialect.do_ping(dbapi_connection)
        except Exception as exc:
            logger.warning(
                "db_stale_connection_replaced",
                extra={
                    "application_name": service_name,
                    "idle_seconds": round(idle_seconds, 1),
                    "error_type": type(exc).__name__,
                },
            )
            raise InvalidatePoolError("idle connection failed its ping") from exc

    event.listen(sync_engine, "checkin", _stamp)
    event.listen(sync_engine, "checkout", _validate)


class OutageTypedAsyncQueuePool(AsyncAdaptedQueuePool):
    def _do_get(self) -> ConnectionPoolEntry:
        try:
            return super()._do_get()
        except PoolTimeoutError as exc:
            raise DatabaseUnavailableError(
                "connection pool exhausted", code=DatabaseOutageCode.POOL_EXHAUSTED
            ) from exc


def create_async_engine_factory(
    database_url: str,
    *,
    statement_timeout_seconds: float,
    service_name: str = "",
    schema: str = "",
    echo: bool = False,
    pool_class: type = OutageTypedAsyncQueuePool,
    connect_args: dict | None = None,
    idle_ping_after_seconds: float = DB_IDLE_PING_AFTER_SECONDS,
    **engine_kwargs,
) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine.

    Args:
        database_url: Postgres connection string (any dialect prefix accepted).
        statement_timeout_seconds: Per-statement cap for this engine's process
            profile. Services pass ``settings.database_statement_timeout_seconds``;
            required, so an engine can never be built without one.
        service_name: Injected as ``application_name`` in ``server_settings``.
            Shows up in ``pg_stat_activity`` to identify the owning service.
        schema: Injected as ``search_path`` (``"{schema},public"``) in
            ``server_settings`` for connection-level schema isolation.
        echo: Echo SQL statements.
        pool_class: Pool implementation. The default keeps ``DEFAULT_POOL_KWARGS``
            warm connections (see the note on that constant); pass ``NullPool``
            for one-shot processes such as the migration runner. The default,
            ``OutageTypedAsyncQueuePool``, raises ``DatabaseUnavailableError`` when a
            checkout waits out ``pool_timeout``; any other pool class raises
            ``ValueError``.
        connect_args: Extra asyncpg connect args **merged** on top of the
            PgBouncer-safe defaults.  The ``server_settings`` sub-dict is
            merged (not replaced), so callers can add keys without losing
            ``jit``, ``application_name``, or ``search_path``.
        idle_ping_after_seconds: A pooled connection unused for at least this long
            is pinged on checkout and replaced if dead.
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
    if not issubclass(pool_class, (OutageTypedAsyncQueuePool, NullPool)):
        raise ValueError(
            f"pool_class={pool_class.__name__} would leave pool exhaustion untyped; "
            "omit pool_class, or pass NullPool"
        )
    if issubclass(pool_class, QueuePool):
        engine_kwargs = {**DEFAULT_POOL_KWARGS, **engine_kwargs}
    engine = create_async_engine(
        _to_asyncpg(database_url),
        echo=echo,
        poolclass=pool_class,
        connect_args=_build_connect_args(
            service_name,
            schema,
            connect_args,
            statement_timeout_seconds=statement_timeout_seconds,
        ),
        **engine_kwargs,
    )
    _install_error_translation(
        engine, service_name=service_name, statement_timeout_seconds=statement_timeout_seconds
    )
    if issubclass(pool_class, QueuePool):
        _install_idle_validation(
            engine, idle_ping_after_seconds=idle_ping_after_seconds, service_name=service_name
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


def _set_local_statement_timeout(statement_timeout_seconds: float) -> str:
    return f"SET LOCAL statement_timeout = {int(statement_timeout_seconds * 1000)}"


def install_transaction_statement_timeout(engine: Engine, statement_timeout_seconds: float) -> None:
    statement = _set_local_statement_timeout(statement_timeout_seconds)

    def _cap(connection: Connection) -> None:
        connection.exec_driver_sql(statement)

    event.listen(engine, "begin", _cap)


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
