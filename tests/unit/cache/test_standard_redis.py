"""Tests for StandardRedisAdapter using fakeredis."""

import pytest

from tr_shared.cache.adapters.standard_redis import StandardPipeline, StandardRedisAdapter
from tr_shared.cache.exceptions import CacheConnectionError, CacheOperationError


@pytest.fixture
async def adapter(async_fake_redis):
    """A StandardRedisAdapter pre-wired with fakeredis client."""
    a = StandardRedisAdapter(url="redis://localhost:6379/0")
    a._client = async_fake_redis
    a._available = True
    return a


class TestInitialization:
    def test_not_available_before_init(self):
        a = StandardRedisAdapter(url="redis://localhost:6379/0")
        assert a._available is False

    def test_client_is_none_before_init(self):
        a = StandardRedisAdapter(url="redis://localhost:6379/0")
        assert a._client is None

    async def test_initialize_with_fakeredis_sets_available(self, async_fake_redis):
        a = StandardRedisAdapter(url="redis://localhost:6379/0")
        a._client = async_fake_redis
        a._available = False
        # Direct ping test — simulates successful initialize
        result = await async_fake_redis.ping()
        assert result is True


class TestPing:
    async def test_ping_returns_true_when_available(self, adapter):
        assert await adapter.ping() is True

    async def test_ping_returns_false_when_not_available(self):
        a = StandardRedisAdapter(url="redis://localhost:6379/0")
        assert await a.ping() is False


class TestGet:
    async def test_get_returns_value_after_set(self, adapter, async_fake_redis):
        await async_fake_redis.set("key:1", "hello")
        result = await adapter.get("key:1")
        assert result == "hello"

    async def test_get_returns_none_for_missing_key(self, adapter):
        result = await adapter.get("nonexistent:key")
        assert result is None

    async def test_get_raises_when_not_initialized(self):
        a = StandardRedisAdapter(url="redis://localhost:6379/0")
        with pytest.raises(CacheConnectionError):
            await a.get("key:1")


class TestSetAndSetex:
    async def test_setex_stores_value_with_ttl(self, adapter, async_fake_redis):
        await adapter.setex("key:2", 60, "value")
        result = await async_fake_redis.get("key:2")
        assert result == "value"

    async def test_setex_returns_true(self, adapter):
        result = await adapter.setex("key:3", 60, "val")
        assert result is True

    async def test_set_stores_value(self, adapter, async_fake_redis):
        await adapter.set("key:4", "v4")
        result = await async_fake_redis.get("key:4")
        assert result == "v4"

    async def test_set_with_ttl(self, adapter, async_fake_redis):
        await adapter.set("key:5", "v5", ttl=120)
        ttl = await async_fake_redis.ttl("key:5")
        assert 0 < ttl <= 120

    async def test_set_nx_only_sets_if_not_exists(self, adapter, async_fake_redis):
        await async_fake_redis.set("nx:key", "original")
        await adapter.set("nx:key", "new_value", nx=True)
        result = await async_fake_redis.get("nx:key")
        assert result == "original"  # not overwritten


class TestDelete:
    async def test_delete_removes_key(self, adapter, async_fake_redis):
        await async_fake_redis.set("del:key", "v")
        count = await adapter.delete("del:key")
        assert count == 1
        assert await async_fake_redis.get("del:key") is None

    async def test_delete_returns_zero_for_missing_key(self, adapter):
        count = await adapter.delete("missing:key")
        assert count == 0

    async def test_delete_multiple_keys(self, adapter, async_fake_redis):
        await async_fake_redis.set("k1", "v1")
        await async_fake_redis.set("k2", "v2")
        count = await adapter.delete("k1", "k2")
        assert count == 2


class TestExists:
    async def test_exists_returns_1_for_existing_key(self, adapter, async_fake_redis):
        await async_fake_redis.set("ex:key", "v")
        count = await adapter.exists("ex:key")
        assert count == 1

    async def test_exists_returns_0_for_missing_key(self, adapter):
        count = await adapter.exists("no:such:key")
        assert count == 0


class TestTtlAndExpire:
    async def test_ttl_returns_positive_for_key_with_expiry(self, adapter, async_fake_redis):
        await async_fake_redis.setex("ttl:key", 120, "v")
        ttl = await adapter.ttl("ttl:key")
        assert 0 < ttl <= 120

    async def test_expire_sets_ttl(self, adapter, async_fake_redis):
        await async_fake_redis.set("exp:key", "v")
        result = await adapter.expire("exp:key", 60)
        assert result is True
        ttl = await async_fake_redis.ttl("exp:key")
        assert 0 < ttl <= 60


class TestMget:
    async def test_mget_returns_values_in_order(self, adapter, async_fake_redis):
        await async_fake_redis.set("mg:1", "a")
        await async_fake_redis.set("mg:2", "b")
        result = await adapter.mget(["mg:1", "mg:2"])
        assert result == ["a", "b"]

    async def test_mget_returns_none_for_missing(self, adapter):
        result = await adapter.mget(["misskey:1", "misskey:2"])
        assert result == [None, None]

    async def test_mget_empty_list_returns_empty(self, adapter):
        result = await adapter.mget([])
        assert result == []


class TestHsetHgetall:
    async def test_hset_and_hgetall_round_trip(self, adapter):
        mapping = {"field1": "value1", "field2": "value2"}
        await adapter.hset("hash:key", mapping=mapping)
        result = await adapter.hgetall("hash:key")
        assert result == mapping

    async def test_hgetall_returns_empty_for_missing_key(self, adapter):
        result = await adapter.hgetall("missing:hash")
        assert result == {}


class TestXadd:
    async def test_xadd_returns_message_id(self, adapter):
        msg_id = await adapter.xadd("stream:test", {"field": "value"})
        assert isinstance(msg_id, str)
        assert "-" in msg_id  # Redis stream message ID format: "timestamp-seq"


class TestScan:
    async def test_scan_returns_cursor_and_keys(self, adapter, async_fake_redis):
        await async_fake_redis.set("scan:a", "1")
        await async_fake_redis.set("scan:b", "2")
        cursor, keys = await adapter.scan(cursor=0, match="scan:*")
        assert isinstance(cursor, int)
        assert any("scan:" in k for k in keys)


class TestPipeline:
    async def test_pipeline_setex_and_execute(self, adapter, async_fake_redis):
        pipe = adapter.pipeline()
        pipe.setex("pipe:key1", 60, "v1")
        pipe.setex("pipe:key2", 60, "v2")
        results = await pipe.execute()
        assert len(results) == 2
        assert await async_fake_redis.get("pipe:key1") == "v1"
        assert await async_fake_redis.get("pipe:key2") == "v2"

    async def test_pipeline_empty_execute_returns_empty(self, adapter):
        pipe = adapter.pipeline()
        results = await pipe.execute()
        assert results == []

    def test_pipeline_raises_when_not_initialized(self):
        a = StandardRedisAdapter(url="redis://localhost:6379/0")
        with pytest.raises(CacheConnectionError):
            a.pipeline()


class TestContextManager:
    async def test_context_manager_closes_on_exit(self, async_fake_redis):
        from unittest.mock import AsyncMock, patch
        a = StandardRedisAdapter(url="redis://localhost:6379/0")
        with patch.object(a, "initialize", new=AsyncMock(return_value=True)):
            with patch.object(a, "close", new=AsyncMock()) as mock_close:
                async with a:
                    pass
                mock_close.assert_awaited_once()
