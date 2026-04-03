"""Tests for database session helpers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tr_shared.db.session import (
    PGBOUNCER_CONNECT_ARGS,
    _to_asyncpg,
    create_async_engine_factory,
    create_session_factory,
    get_db,
)


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------

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
        url = "sqlite+aiosqlite:///test.db"
        assert _to_asyncpg(url) == url


# ---------------------------------------------------------------------------
# PGBOUNCER_CONNECT_ARGS
# ---------------------------------------------------------------------------

class TestPgbouncerConnectArgs:
    def test_statement_cache_size_is_zero(self):
        assert PGBOUNCER_CONNECT_ARGS["statement_cache_size"] == 0

    def test_prepared_statement_cache_size_is_zero(self):
        assert PGBOUNCER_CONNECT_ARGS["prepared_statement_cache_size"] == 0

    def test_jit_is_off(self):
        assert PGBOUNCER_CONNECT_ARGS["server_settings"]["jit"] == "off"


# ---------------------------------------------------------------------------
# Engine + session factory creation (no actual DB connection)
# ---------------------------------------------------------------------------

class TestCreateAsyncEngineFactory:
    def test_returns_async_engine(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert isinstance(engine, AsyncEngine)

    def test_echo_default_is_false(self):
        engine = create_async_engine_factory("postgresql+asyncpg://localhost/test")
        assert engine.echo is False

    def test_echo_true_propagated(self):
        engine = create_async_engine_factory(
            "postgresql+asyncpg://localhost/test", echo=True
        )
        assert engine.echo is True

    def test_normalises_postgres_url(self):
        # Should not raise — _to_asyncpg is applied internally
        engine = create_async_engine_factory("postgres://user:pw@localhost/db")
        assert isinstance(engine, AsyncEngine)


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


# ---------------------------------------------------------------------------
# get_db dependency
# ---------------------------------------------------------------------------

class TestGetDb:
    async def test_raises_runtime_error_when_no_factory(self):
        with pytest.raises(RuntimeError, match="session_factory"):
            async for _ in get_db():
                pass  # Should raise before yielding

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
