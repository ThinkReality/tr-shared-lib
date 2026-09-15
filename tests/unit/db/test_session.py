"""Tests for database session helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from tr_shared.config import BaseServiceSettings
from tr_shared.contracts.db_pool import DEFAULT_MAX_OVERFLOW, DEFAULT_POOL_SIZE
from tr_shared.db.session import (
    PGBOUNCER_CONNECT_ARGS,
    _build_connect_args,
    _to_asyncpg,
    create_async_engine_factory,
    create_session_factory,
    dispose_engines_after_fork,
    get_db,
)


class TestToAsyncpg:
    def test_already_asyncpg_unchanged(self):
        url = "postgresql+asyncpg://user:pw@localhost/db"
        assert _to_asyncpg(url) == url

    def test_postgresql_dialect_converted(self):
        url = "postgresql://user:pw@localhost/db"
        result = _to_asyncpg(url)
        assert result.startswith("postgresql+asyncpg://")

    def test_postgres_shorthand_converted(self):
        url = "postgres://user:pw@localhost/db"
        result = _to_asyncpg(url)
        assert result.startswith("postgresql+asyncpg://")

    def test_postgres_shorthand_preserves_rest_of_url(self):
        url = "postgres://user:pw@myhost:5432/mydb"
        result = _to_asyncpg(url)
        assert "myhost:5432/mydb" in result

    def test_other_scheme_returned_as_is(self):
        # Any non-Postgres scheme proves the passthrough branch. This used to say
        # `sqlite+aiosqlite://` — the one thing the library's own G2 guard bans
        # fleet-wide, sitting in the library that ships the guard. The assertion
        # never cared which scheme it was.
        url = "mysql+aiomysql://user:pw@localhost/db"
        assert _to_asyncpg(url) == url


class TestPgbouncerConnectArgs:
    def test_statement_cache_size_is_zero(self):
        assert PGBOUNCER_CONNECT_ARGS["statement_cache_size"] == 0

    def test_prepared_statement_cache_size_is_zero(self):
        assert PGBOUNCER_CONNECT_ARGS["prepared_statement_cache_size"] == 0

    def test_jit_is_off(self):
        assert PGBOUNCER_CONNECT_ARGS["server_settings"]["jit"] == "off"


class TestBuildConnectArgs:
    def test_no_overrides_matches_defaults(self):
        result = _build_connect_args("", "", None)
        assert result["statement_cache_size"] == PGBOUNCER_CONNECT_ARGS["statement_cache_size"]
        assert (
            result["prepared_statement_cache_size"]
            == PGBOUNCER_CONNECT_ARGS["prepared_statement_cache_size"]
        )
        assert result["command_timeout"] == PGBOUNCER_CONNECT_ARGS["command_timeout"]
        assert result["server_settings"]["jit"] == "off"

    def test_returns_deep_copy(self):
        result = _build_connect_args("", "", None)
        result["statement_cache_size"] = 999
        result["server_settings"]["jit"] = "on"
        assert PGBOUNCER_CONNECT_ARGS["statement_cache_size"] == 0
        assert PGBOUNCER_CONNECT_ARGS["server_settings"]["jit"] == "off"

    def test_service_name_sets_application_name(self):
        result = _build_connect_args("crm-backend", "", None)
        assert result["server_settings"]["application_name"] == "crm-backend"
        assert result["server_settings"]["jit"] == "off"

    def test_schema_sets_search_path(self):
        result = _build_connect_args("", "lead", None)
        assert result["server_settings"]["search_path"] == "lead,public"
        assert result["server_settings"]["jit"] == "off"

    def test_both_service_name_and_schema(self):
        result = _build_connect_args("crm-backend", "auth_schema", None)
        assert result["server_settings"]["application_name"] == "crm-backend"
        assert result["server_settings"]["search_path"] == "auth_schema,public"
        assert result["server_settings"]["jit"] == "off"

    def test_empty_strings_do_not_inject(self):
        result = _build_connect_args("", "", None)
        assert "application_name" not in result["server_settings"]
        assert "search_path" not in result["server_settings"]

    def test_custom_connect_args_merges_with_defaults(self):
        result = _build_connect_args("", "", {"command_timeout": 120})
        assert result["command_timeout"] == 120
        assert result["statement_cache_size"] == 0
        assert result["prepared_statement_cache_size"] == 0

    def test_custom_connect_args_can_override_defaults(self):
        result = _build_connect_args("", "", {"command_timeout": 120})
        assert result["command_timeout"] == 120

    def test_custom_server_settings_merges_not_replaces(self):
        result = _build_connect_args(
            "admin-panel",
            "admin",
            {"server_settings": {"plan_cache_mode": "force_custom_plan"}},
        )
        assert result["server_settings"]["plan_cache_mode"] == "force_custom_plan"
        assert result["server_settings"]["jit"] == "off"
        assert result["server_settings"]["application_name"] == "admin-panel"
        assert result["server_settings"]["search_path"] == "admin,public"

    def test_pgbouncer_safe_keys_always_present(self):
        result = _build_connect_args(
            "test",
            "test_schema",
            {"command_timeout": 120, "server_settings": {"extra": "value"}},
        )
        assert result["statement_cache_size"] == 0
        assert result["prepared_statement_cache_size"] == 0
        assert callable(result["prepared_statement_name_func"])
        assert result["prepared_statement_name_func"]() == ""


class TestCreateAsyncEngineFactory:
    def test_returns_async_engine(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert isinstance(engine, AsyncEngine)

    def test_echo_default_is_false(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert engine.echo is False

    def test_echo_true_propagated(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test", echo=True)
        assert engine.echo is True

    def test_normalises_postgres_url(self):
        engine = create_async_engine_factory("postgres://user:pw@localhost/db")
        assert isinstance(engine, AsyncEngine)

    def test_service_name_sets_application_name(self):
        engine = create_async_engine_factory(
            "postgresql+asyncpg://localhost/test",
            service_name="crm-backend",
        )
        assert isinstance(engine, AsyncEngine)

    def test_schema_sets_search_path(self):
        engine = create_async_engine_factory(
            "postgresql+asyncpg://localhost/test",
            schema="lead",
        )
        assert isinstance(engine, AsyncEngine)

    def test_both_service_name_and_schema(self):
        engine = create_async_engine_factory(
            "postgresql+asyncpg://localhost/test",
            service_name="lead",
            schema="lead",
        )
        assert isinstance(engine, AsyncEngine)

    def test_custom_connect_args_merge_preserves_defaults(self):
        engine = create_async_engine_factory(
            "postgresql+asyncpg://localhost/test",
            service_name="admin-panel",
            schema="admin",
            connect_args={"server_settings": {"plan_cache_mode": "force_custom_plan"}},
        )
        assert isinstance(engine, AsyncEngine)

    def test_defaults_preserved_when_no_new_params(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert isinstance(engine, AsyncEngine)
        assert engine.echo is False


class TestConnectionPoolDefaults:
    """A long-lived container keeps a small pool of warm connections.

    NullPool paid a full TCP + TLS + SCRAM handshake plus asyncpg's type introspection on
    every request — six or so round trips before the first statement, ~450 ms with the
    database one region away. Resting size is what the Supavisor client cap (200 on the
    smallest compute) must absorb: every uvicorn worker AND every Celery prefork child is
    a process with its own pool, ~52 engines fleet-wide × 2 ≈ 104. Overflow is burst room
    that is released on return; 8 lets two API workers take the board's 20 parallel page
    fetches without a checkout ever waiting.
    """

    def test_default_pool_keeps_connections(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert isinstance(engine.pool, AsyncAdaptedQueuePool)

    def test_default_pool_is_sized_for_the_pooler_client_cap(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert engine.pool.size() == DEFAULT_POOL_SIZE == 2
        assert engine.pool._max_overflow == DEFAULT_MAX_OVERFLOW == 8
        assert engine.pool._timeout == 10

    def test_connections_are_recycled_before_an_idle_socket_can_go_stale(self):
        # Recycle bounds idle time from above (idle ≤ age), and 300 s sits under the
        # ~350 s cloud NAT idle timeouts — the reason to drop pre-ping (below).
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert engine.pool._recycle == 300

    def test_pre_ping_is_off(self):
        # Under asyncpg in pgbouncer mode a pre-ping is BEGIN + fetchrow(";") + ROLLBACK
        # on every checkout — four round trips, invisible to cursor-level instrumentation.
        # That is most of what pooling saves; recycle carries the staleness guard instead.
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert engine.pool._pre_ping is False

    def test_sizing_can_be_overridden_per_engine(self):
        engine = create_async_engine_factory(
            "postgresql+asyncpg://localhost/test", pool_size=4, max_overflow=0
        )
        assert engine.pool.size() == 4
        assert engine.pool._max_overflow == 0

    def test_null_pool_still_available_and_takes_no_sizing(self):
        # Migration runner and test fixtures ask for NullPool; SQLAlchemy rejects
        # pool_size/max_overflow on it, so the defaults must not be applied there.
        engine = create_async_engine_factory(
            "postgresql+asyncpg://localhost/test", pool_class=NullPool
        )
        assert isinstance(engine.pool, NullPool)

    def test_factory_engines_drop_inherited_connections_after_fork(self, monkeypatch):
        # Celery prefork children inherit the parent's pool; a checked-in socket used
        # from two processes is silent corruption. SQLAlchemy's prescription is
        # ``dispose(close=False)`` in the child — for every engine the factory made.
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        calls: list[dict] = []
        monkeypatch.setattr(
            engine.sync_engine, "dispose", lambda **kw: calls.append(kw), raising=True
        )

        dispose_engines_after_fork()

        assert calls == [{"close": False}]

    def test_settings_defaults_mirror_the_factory(self):
        # Services that forward DATABASE_POOL_SIZE/MAX_OVERFLOW from settings must get
        # the same numbers as services that pass nothing — one policy, two entry points.
        s = BaseServiceSettings(SERVICE_NAME="test-svc")
        assert s.DATABASE_POOL_SIZE == DEFAULT_POOL_SIZE
        assert s.DATABASE_MAX_OVERFLOW == DEFAULT_MAX_OVERFLOW


class TestCreateSessionFactory:
    def test_returns_async_sessionmaker(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        factory = create_session_factory(engine)
        assert isinstance(factory, async_sessionmaker)

    def test_expire_on_commit_is_false(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        factory = create_session_factory(engine)
        assert factory.kw.get("expire_on_commit") is False

    def test_autoflush_is_false(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        factory = create_session_factory(engine)
        assert factory.kw.get("autoflush") is False


class TestGetDb:
    async def test_raises_runtime_error_when_no_factory(self):
        with pytest.raises(RuntimeError, match="session_factory"):
            async for _ in get_db():
                pass

    async def test_yields_session_from_factory(self):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        yielded = []
        async for session in get_db(session_factory=mock_factory):
            yielded.append(session)
        assert len(yielded) == 1
        assert yielded[0] is mock_session
