"""Tests for BaseRedisAdapter shared behaviour.

Verifies that the guard, error-wrapping, and empty-collection-guard logic
in the base class works correctly, using a minimal concrete subclass
backed by fakeredis so no real Redis server is needed.
"""

import pytest
import fakeredis.aioredis as fakeredis

from tr_shared.cache.adapters.base import BaseRedisAdapter
from tr_shared.cache.exceptions import CacheConnectionError, CacheOperationError
from tr_shared.cache.interface import PipelineInterface


# ---------------------------------------------------------------------------
# Minimal concrete subclass — delegates all abstract methods to fakeredis
# ---------------------------------------------------------------------------

class _FakeAdapter(BaseRedisAdapter):
    """Thin concrete adapter used only in these tests."""

    def __init__(self, pre_initialized: bool = True) -> None:
        self._client = None
        self._available = False
        if pre_initialized:
            self._client = fakeredis.FakeRedis(decode_responses=True)
            self._available = True

    async def initialize(self) -> bool:
        self._client = fakeredis.FakeRedis(decode_responses=True)
        self._available = True
        return True

    async def close(self) -> None:
        self._client = None
        self._available = False

    async def ping(self) -> bool:
        return self._available

    async def set(
        self, key: str, value: str, ttl: int | None = None, nx: bool = False
    ) -> bool:
        self._check_initialized("set")
        try:
            result = await self._client.set(key, value, ex=ttl, nx=nx or None)
            return result is not None
        except Exception as e:
            raise CacheOperationError(f"SET failed: {e}") from e

    async def xadd(self, stream, fields, maxlen=None):
        self._check_initialized("xadd")
        try:
            return await self._client.xadd(stream, fields)
        except Exception as e:
            raise CacheOperationError(f"XADD failed: {e}") from e

    def pipeline(self) -> PipelineInterface:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Guard tests — calling methods before initialize() raises CacheConnectionError
# ---------------------------------------------------------------------------

class TestGuard:
    async def test_get_raises_when_not_initialized(self):
        adapter = _FakeAdapter(pre_initialized=False)
        with pytest.raises(CacheConnectionError):
            await adapter.get("key")

    async def test_setex_raises_when_not_initialized(self):
        adapter = _FakeAdapter(pre_initialized=False)
        with pytest.raises(CacheConnectionError):
            await adapter.setex("key", 10, "value")

    async def test_delete_raises_when_not_initialized(self):
        adapter = _FakeAdapter(pre_initialized=False)
        with pytest.raises(CacheConnectionError):
            await adapter.delete("key")

    async def test_exists_raises_when_not_initialized(self):
        adapter = _FakeAdapter(pre_initialized=False)
        with pytest.raises(CacheConnectionError):
            await adapter.exists("key")

    async def test_scan_raises_when_not_initialized(self):
        adapter = _FakeAdapter(pre_initialized=False)
        with pytest.raises(CacheConnectionError):
            await adapter.scan()


# ---------------------------------------------------------------------------
# Empty-collection guard — should return early without hitting Redis
# ---------------------------------------------------------------------------

class TestEmptyCollectionGuard:
    async def test_delete_no_keys_returns_zero(self):
        adapter = _FakeAdapter()
        result = await adapter.delete()
        assert result == 0

    async def test_exists_no_keys_returns_zero(self):
        adapter = _FakeAdapter()
        result = await adapter.exists()
        assert result == 0

    async def test_mget_empty_list_returns_empty(self):
        adapter = _FakeAdapter()
        result = await adapter.mget([])
        assert result == []


# ---------------------------------------------------------------------------
# Correct delegation — methods actually call through to Redis
# ---------------------------------------------------------------------------

class TestDelegation:
    async def test_get_returns_none_on_miss(self):
        adapter = _FakeAdapter()
        assert await adapter.get("missing") is None

    async def test_setex_and_get_round_trip(self):
        adapter = _FakeAdapter()
        await adapter.setex("k", 60, "hello")
        assert await adapter.get("k") == "hello"

    async def test_delete_removes_key(self):
        adapter = _FakeAdapter()
        await adapter.setex("k", 60, "v")
        deleted = await adapter.delete("k")
        assert deleted == 1
        assert await adapter.get("k") is None

    async def test_hgetall_returns_empty_dict_on_miss(self):
        adapter = _FakeAdapter()
        result = await adapter.hgetall("nonexistent")
        assert result == {}

    async def test_hset_and_hgetall_round_trip(self):
        adapter = _FakeAdapter()
        await adapter.hset("h", {"field": "value"})
        result = await adapter.hgetall("h")
        assert result["field"] == "value"

    async def test_mget_returns_values_in_order(self):
        adapter = _FakeAdapter()
        await adapter.setex("a", 60, "1")
        await adapter.setex("b", 60, "2")
        results = await adapter.mget(["a", "b", "missing"])
        assert results[0] == "1"
        assert results[1] == "2"
        assert results[2] is None

    async def test_expire_and_ttl(self):
        adapter = _FakeAdapter()
        await adapter.setex("k", 9999, "v")
        await adapter.expire("k", 100)
        remaining = await adapter.ttl("k")
        assert 0 < remaining <= 100

    async def test_exists_returns_count(self):
        adapter = _FakeAdapter()
        await adapter.setex("a", 60, "1")
        assert await adapter.exists("a") == 1
        assert await adapter.exists("missing") == 0


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    async def test_aenter_aexit_round_trip(self):
        adapter = _FakeAdapter(pre_initialized=False)
        async with adapter as a:
            assert a._available is True
        assert adapter._available is False
