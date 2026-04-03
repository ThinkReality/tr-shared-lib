"""Tests for UpstashAdapter — mocks upstash_redis so no SDK install required."""

import importlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to inject a fake upstash_redis into sys.modules before loading
# ---------------------------------------------------------------------------

def _make_fake_upstash_modules() -> dict:
    """Return fake sys.modules entries that satisfy the upstash_redis import."""
    fake_redis_instance = AsyncMock()
    fake_redis_cls = MagicMock(return_value=fake_redis_instance)
    fake_pipeline = MagicMock()

    fake_asyncio = ModuleType("upstash_redis.asyncio")
    fake_asyncio.Redis = fake_redis_cls

    fake_asyncio_client = ModuleType("upstash_redis.asyncio.client")
    fake_asyncio_client.AsyncPipeline = fake_pipeline

    fake_root = ModuleType("upstash_redis")

    return {
        "upstash_redis": fake_root,
        "upstash_redis.asyncio": fake_asyncio,
        "upstash_redis.asyncio.client": fake_asyncio_client,
    }


def _load_upstash_adapter():
    """Import UpstashAdapter with fake upstash_redis in sys.modules."""
    fake_modules = _make_fake_upstash_modules()
    # Remove any previously cached version so the reload is clean
    for key in list(sys.modules.keys()):
        if "upstash" in key:
            del sys.modules[key]

    with patch.dict("sys.modules", fake_modules):
        import tr_shared.cache.adapters.upstash as mod
        importlib.reload(mod)
        return mod


@pytest.fixture
def upstash_mod():
    """Return a freshly loaded upstash adapter module with mocked SDK."""
    return _load_upstash_adapter()


@pytest.fixture
def mock_client():
    """A fully async-mocked upstash client."""
    client = AsyncMock()
    client.ping = AsyncMock(return_value="PONG")
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value="OK")
    client.setex = AsyncMock(return_value="OK")
    client.delete = AsyncMock(return_value=1)
    client.exists = AsyncMock(return_value=1)
    client.ttl = AsyncMock(return_value=60)
    client.expire = AsyncMock(return_value=1)
    client.mget = AsyncMock(return_value=[None, None])
    client.hgetall = AsyncMock(return_value={})
    client.hset = AsyncMock(return_value=1)
    client.xadd = AsyncMock(return_value="1234567890-0")
    client.scan = AsyncMock(return_value=(0, []))
    pipe = MagicMock()
    pipe.exec = AsyncMock(return_value=[True, True])
    pipe.setex = MagicMock(return_value=pipe)
    client.pipeline = MagicMock(return_value=pipe)
    return client


@pytest.fixture
def adapter(upstash_mod, mock_client):
    """UpstashAdapter pre-wired with a mock client."""
    a = upstash_mod.UpstashAdapter(
        rest_url="https://example.upstash.io",
        rest_token="token-123",
    )
    a._client = mock_client
    a._available = True
    return a


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_not_available_before_init(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(
            rest_url="https://x.upstash.io", rest_token="tok"
        )
        assert a._available is False

    def test_client_is_none_before_init(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(
            rest_url="https://x.upstash.io", rest_token="tok"
        )
        assert a._client is None

    async def test_initialize_sets_available_on_success(self, upstash_mod, mock_client):
        # Patch AsyncUpstashRedis directly on the already-loaded module
        with patch.object(upstash_mod, "AsyncUpstashRedis", return_value=mock_client):
            a = upstash_mod.UpstashAdapter(
                rest_url="https://x.upstash.io", rest_token="tok"
            )
            result = await a.initialize()
            assert result is True
            assert a._available is True

    async def test_initialize_returns_false_on_failure(self, upstash_mod):
        fake_client = AsyncMock()
        fake_client.ping = AsyncMock(side_effect=Exception("Connection refused"))
        with patch.object(upstash_mod, "AsyncUpstashRedis", return_value=fake_client):
            a = upstash_mod.UpstashAdapter(
                rest_url="https://x.upstash.io", rest_token="tok"
            )
            result = await a.initialize()
            assert result is False
            assert a._available is False


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------

class TestPing:
    async def test_ping_returns_true_when_available(self, adapter, mock_client):
        mock_client.ping.return_value = "PONG"
        assert await adapter.ping() is True

    async def test_ping_returns_false_when_not_available(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(
            rest_url="https://x.upstash.io", rest_token="tok"
        )
        assert await a.ping() is False

    async def test_ping_returns_false_on_exception(self, adapter, mock_client):
        mock_client.ping.side_effect = Exception("network error")
        assert await adapter.ping() is False


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestGet:
    async def test_get_returns_value(self, adapter, mock_client):
        mock_client.get.return_value = "hello"
        result = await adapter.get("key:1")
        assert result == "hello"
        mock_client.get.assert_awaited_once_with("key:1")

    async def test_get_returns_none_for_missing(self, adapter, mock_client):
        mock_client.get.return_value = None
        result = await adapter.get("missing")
        assert result is None

    async def test_get_raises_when_not_initialized(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(rest_url="u", rest_token="t")
        # Use Exception base class with match to avoid class-identity issues from reload
        with pytest.raises(Exception, match="not initialized"):
            await a.get("key")

    async def test_get_raises_cache_operation_error_on_exception(self, adapter, mock_client):
        mock_client.get.side_effect = Exception("Redis error")
        with pytest.raises(Exception, match="GET failed"):
            await adapter.get("key:1")


# ---------------------------------------------------------------------------
# Set / Setex
# ---------------------------------------------------------------------------

class TestSetAndSetex:
    async def test_setex_returns_true(self, adapter, mock_client):
        mock_client.setex.return_value = "OK"
        result = await adapter.setex("key:1", 60, "value")
        assert result is True
        mock_client.setex.assert_awaited_once_with("key:1", 60, "value")

    async def test_setex_raises_when_not_initialized(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(rest_url="u", rest_token="t")
        with pytest.raises(Exception, match="not initialized"):
            await a.setex("key", 60, "val")

    async def test_set_without_ttl(self, adapter, mock_client):
        mock_client.set.return_value = "OK"
        result = await adapter.set("key:2", "v2")
        assert result is True
        mock_client.set.assert_awaited_once_with("key:2", "v2")

    async def test_set_with_ttl_calls_setex(self, adapter, mock_client):
        mock_client.setex.return_value = "OK"
        await adapter.set("key:3", "v3", ttl=120)
        mock_client.setex.assert_awaited_once_with("key:3", 120, "v3")

    async def test_set_nx_calls_setnx(self, adapter, mock_client):
        mock_client.setnx = AsyncMock(return_value=1)
        await adapter.set("key:nx", "v", nx=True)
        mock_client.setnx.assert_awaited_once_with("key:nx", "v")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDelete:
    async def test_delete_returns_count(self, adapter, mock_client):
        mock_client.delete.return_value = 1
        count = await adapter.delete("del:key")
        assert count == 1

    async def test_delete_multiple_keys(self, adapter, mock_client):
        mock_client.delete.return_value = 2
        count = await adapter.delete("k1", "k2")
        assert count == 2
        mock_client.delete.assert_awaited_once_with("k1", "k2")

    async def test_delete_raises_when_not_initialized(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(rest_url="u", rest_token="t")
        with pytest.raises(Exception, match="not initialized"):
            await a.delete("key")


# ---------------------------------------------------------------------------
# Exists / TTL / Expire
# ---------------------------------------------------------------------------

class TestExistsTtlExpire:
    async def test_exists_returns_count(self, adapter, mock_client):
        mock_client.exists.return_value = 1
        count = await adapter.exists("key:1")
        assert count == 1

    async def test_ttl_returns_positive(self, adapter, mock_client):
        mock_client.ttl.return_value = 55
        result = await adapter.ttl("key:1")
        assert result == 55

    async def test_expire_returns_true(self, adapter, mock_client):
        mock_client.expire.return_value = 1
        result = await adapter.expire("key:1", 60)
        assert result is True


# ---------------------------------------------------------------------------
# Mget / Hset / Hgetall
# ---------------------------------------------------------------------------

class TestMgetHset:
    async def test_mget_returns_list(self, adapter, mock_client):
        mock_client.mget.return_value = ["v1", None, "v3"]
        result = await adapter.mget(["k1", "k2", "k3"])
        assert result == ["v1", None, "v3"]

    async def test_mget_empty_returns_empty(self, adapter, mock_client):
        result = await adapter.mget([])
        assert result == []
        mock_client.mget.assert_not_called()

    async def test_hset_and_hgetall_round_trip(self, adapter, mock_client):
        mapping = {"f1": "v1", "f2": "v2"}
        mock_client.hset.return_value = 2
        mock_client.hgetall.return_value = mapping
        await adapter.hset("hash:key", mapping=mapping)
        result = await adapter.hgetall("hash:key")
        assert result == mapping

    async def test_hgetall_returns_empty_for_missing(self, adapter, mock_client):
        mock_client.hgetall.return_value = None
        result = await adapter.hgetall("missing")
        assert result == {}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    def test_pipeline_raises_when_not_initialized(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(rest_url="u", rest_token="t")
        with pytest.raises(Exception, match="not initialized"):
            a.pipeline()

    async def test_pipeline_execute_calls_exec(self, adapter, mock_client):
        pipe_obj = adapter.pipeline()
        pipe_obj.setex("key:1", 60, "v1")
        results = await pipe_obj.execute()
        assert results == [True, True]


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    async def test_context_manager_calls_initialize_and_close(self, upstash_mod):
        a = upstash_mod.UpstashAdapter(rest_url="u", rest_token="t")
        with patch.object(a, "initialize", new=AsyncMock(return_value=True)):
            with patch.object(a, "close", new=AsyncMock()) as mock_close:
                async with a:
                    pass
                mock_close.assert_awaited_once()
