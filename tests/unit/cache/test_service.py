"""Tests for CacheService — JSON serialization, get/set/delete, cache-aside, key building."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tr_shared.cache.service import CacheResult, CacheService


def _mock_cache() -> MagicMock:
    """Build a mock CacheInterface."""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.mget = AsyncMock(return_value=[])
    cache.setex = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=1)
    cache.scan = AsyncMock(return_value=(0, []))
    pipe = MagicMock()
    pipe.setex = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[True])
    cache.pipeline = MagicMock(return_value=pipe)
    return cache


class TestGet:
    async def test_returns_deserialized_value_on_hit(self):
        cache = _mock_cache()
        cache.get.return_value = json.dumps({"name": "Listing A"})
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get("key:1")
        assert result == {"name": "Listing A"}

    async def test_returns_none_on_miss(self):
        cache = _mock_cache()
        cache.get.return_value = None
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get("key:missing")
        assert result is None

    async def test_returns_none_silently_on_redis_error(self):
        cache = _mock_cache()
        cache.get.side_effect = Exception("Redis unavailable")
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get("key:error")
        assert result is None  # silent fail, no exception raised

    async def test_returns_primitive_types(self):
        cache = _mock_cache()
        cache.get.return_value = json.dumps(42)
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get("key:int")
        assert result == 42


class TestGetMany:
    async def test_returns_dict_with_deserialized_values(self):
        cache = _mock_cache()
        cache.mget.return_value = [json.dumps("val1"), json.dumps("val2")]
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get_many(["k1", "k2"])
        assert result == {"k1": "val1", "k2": "val2"}

    async def test_returns_none_for_missing_keys(self):
        cache = _mock_cache()
        cache.mget.return_value = [json.dumps("val1"), None]
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get_many(["k1", "k2"])
        assert result["k1"] == "val1"
        assert result["k2"] is None

    async def test_returns_empty_dict_for_empty_keys(self):
        cache = _mock_cache()
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get_many([])
        assert result == {}

    async def test_returns_none_map_on_redis_error(self):
        cache = _mock_cache()
        cache.mget.side_effect = Exception("Redis error")
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get_many(["k1", "k2"])
        assert result == {"k1": None, "k2": None}


class TestGetOrSet:
    async def test_returns_cached_value_without_calling_fetch_func(self):
        cache = _mock_cache()
        cache.get.return_value = json.dumps({"id": 1})
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        fetch_func = AsyncMock(return_value={"id": 999})
        result = await svc.get_or_set("key:1", fetch_func=fetch_func, ttl=60)
        assert result == {"id": 1}
        fetch_func.assert_not_called()

    async def test_calls_fetch_func_on_miss_and_caches_result(self):
        cache = _mock_cache()
        cache.get.return_value = None
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        fetch_func = AsyncMock(return_value={"id": 42})
        result = await svc.get_or_set("key:1", fetch_func=fetch_func, ttl=300)
        assert result == {"id": 42}
        fetch_func.assert_awaited_once()
        cache.setex.assert_awaited_once()

    async def test_calls_fetch_func_on_cache_error(self):
        cache = _mock_cache()
        cache.get.side_effect = Exception("Redis error")
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        fetch_func = AsyncMock(return_value={"fallback": True})
        result = await svc.get_or_set("key:1", fetch_func=fetch_func)
        assert result == {"fallback": True}
        fetch_func.assert_awaited_once()

    async def test_does_not_cache_none_result(self):
        cache = _mock_cache()
        cache.get.return_value = None
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        fetch_func = AsyncMock(return_value=None)
        await svc.get_or_set("key:1", fetch_func=fetch_func)
        cache.setex.assert_not_called()


class TestSet:
    async def test_serializes_to_json_and_stores_with_ttl(self):
        cache = _mock_cache()
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        await svc.set("key:1", {"name": "test"}, ttl=120)
        cache.setex.assert_awaited_once()
        call_args = cache.setex.call_args
        assert call_args[0][0] == "key:1"
        assert call_args[0][1] == 120
        assert json.loads(call_args[0][2]) == {"name": "test"}

    async def test_does_not_raise_on_redis_error(self):
        cache = _mock_cache()
        cache.setex.side_effect = Exception("Redis error")
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        await svc.set("key:1", {"data": "value"})  # should not raise

    async def test_default_ttl_is_3600(self):
        cache = _mock_cache()
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        await svc.set("key:1", "value")
        call_args = cache.setex.call_args
        assert call_args[0][1] == 3600


class TestSetMany:
    async def test_caches_all_items(self):
        cache = _mock_cache()
        pipe = cache.pipeline.return_value
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        count = await svc.set_many({"k1": "v1", "k2": "v2"}, ttl=60)
        assert count == 2
        assert pipe.setex.call_count == 2
        pipe.execute.assert_awaited_once()

    async def test_returns_zero_for_empty_dict(self):
        cache = _mock_cache()
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        count = await svc.set_many({})
        assert count == 0

    async def test_returns_zero_on_error(self):
        cache = _mock_cache()
        pipe = cache.pipeline.return_value
        pipe.execute.side_effect = Exception("Pipeline error")
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        count = await svc.set_many({"k1": "v1"})
        assert count == 0


class TestDelete:
    async def test_calls_delete_on_cache(self):
        cache = _mock_cache()
        cache.delete.return_value = 1
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        await svc.delete("key:1", "key:2")
        cache.delete.assert_awaited_once_with("key:1", "key:2")

    async def test_does_not_call_delete_for_empty_keys(self):
        cache = _mock_cache()
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        await svc.delete()
        cache.delete.assert_not_called()

    async def test_delete_pattern_returns_count(self):
        cache = _mock_cache()
        cache.scan.side_effect = [
            (0, ["dev:svc:listing:1", "dev:svc:listing:2"]),
        ]
        cache.delete.return_value = 2
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        count = await svc.delete_pattern("dev:svc:listing:*")
        assert count == 2

    async def test_delete_pattern_handles_multiple_scan_pages(self):
        cache = _mock_cache()
        cache.scan.side_effect = [
            (42, ["key:1"]),   # cursor != 0, more pages
            (0, ["key:2"]),    # cursor == 0, done
        ]
        cache.delete.return_value = 1
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        count = await svc.delete_pattern("key:*")
        assert count == 2


class TestBuildKey:
    def test_joins_parts_with_prefix(self):
        svc = CacheService(cache=MagicMock(), key_prefix="dev:svc")
        key = svc.build_key("listings", "123")
        assert key == "dev:svc:listings:123"

    def test_ignores_none_parts(self):
        svc = CacheService(cache=MagicMock(), key_prefix="dev:svc")
        key = svc.build_key("listings", None, "123")
        assert key == "dev:svc:listings:123"

    def test_build_list_key_without_filters(self):
        svc = CacheService(cache=MagicMock(), key_prefix="dev:svc")
        key = svc.build_list_key("listings")
        assert key == "dev:svc:listings:list:all"

    def test_build_list_key_with_filters_is_stable(self):
        svc = CacheService(cache=MagicMock(), key_prefix="dev:svc")
        key1 = svc.build_list_key("listings", filters={"status": "active", "city": "Dubai"})
        key2 = svc.build_list_key("listings", filters={"city": "Dubai", "status": "active"})
        assert key1 == key2  # same filters in different order → same key

    def test_build_list_key_different_filters_differ(self):
        svc = CacheService(cache=MagicMock(), key_prefix="dev:svc")
        key1 = svc.build_list_key("listings", filters={"status": "active"})
        key2 = svc.build_list_key("listings", filters={"status": "inactive"})
        assert key1 != key2


class TestGetResult:
    async def test_hit_returns_hit_true_and_no_error(self):
        cache = _mock_cache()
        cache.get.return_value = json.dumps({"id": 1})
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get_result("some:key")
        assert isinstance(result, CacheResult)
        assert result.hit is True
        assert result.value == {"id": 1}
        assert result.error is None

    async def test_miss_returns_hit_false_and_no_error(self):
        cache = _mock_cache()
        cache.get.return_value = None
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get_result("some:key")
        assert result.hit is False
        assert result.value is None
        assert result.error is None

    async def test_redis_error_returns_error_not_none(self):
        cache = _mock_cache()
        cache.get.side_effect = ConnectionError("Redis is down")
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        result = await svc.get_result("some:key")
        assert result.hit is False
        assert result.value is None
        assert isinstance(result.error, ConnectionError)

    async def test_existing_get_still_returns_none_on_error(self):
        """get() is unchanged — backward compatible."""
        cache = _mock_cache()
        cache.get.side_effect = ConnectionError("Redis is down")
        svc = CacheService(cache=cache, key_prefix="dev:svc")
        value = await svc.get("some:key")
        assert value is None
