"""Tests for cache helper utility functions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tr_shared.cache.helpers import (
    build_cache_key,
    build_entity_cache_key,
    build_list_cache_key,
    invalidate_entity_cache,
    invalidate_list_caches,
    invalidate_pattern,
)


class TestBuildCacheKey:
    def test_joins_parts_with_prefix(self):
        key = build_cache_key("listings", "123", prefix="dev:svc")
        assert key == "dev:svc:listings:123"

    def test_single_part(self):
        key = build_cache_key("health", prefix="dev:svc")
        assert key == "dev:svc:health"

    def test_ignores_none_parts(self):
        key = build_cache_key("entity", None, "456", prefix="dev:svc")
        assert key == "dev:svc:entity:456"

    def test_empty_prefix_still_works(self):
        key = build_cache_key("listings", prefix="")
        assert key == ":listings"


class TestBuildEntityCacheKey:
    def test_includes_entity_and_identifier(self):
        key = build_entity_cache_key("listings", "abc-123", prefix="dev:svc")
        assert "listings" in key
        assert "abc-123" in key

    def test_includes_tenant_id_when_provided(self):
        key = build_entity_cache_key("listings", "abc-123", tenant_id="t1", prefix="dev:svc")
        assert "t1" in key

    def test_no_tenant_id_excludes_it(self):
        key = build_entity_cache_key("listings", "abc-123", prefix="dev:svc")
        assert key == "dev:svc:listings:abc-123"

    def test_with_tenant_has_three_segments(self):
        key = build_entity_cache_key("leads", "lead-1", tenant_id="tenant-1", prefix="p")
        assert key == "p:leads:tenant-1:lead-1"


class TestBuildListCacheKey:
    def test_no_filters_returns_all_key(self):
        key = build_list_cache_key("listings", prefix="dev:svc")
        assert key == "dev:svc:listings:list:all"

    def test_filters_produce_stable_key(self):
        key1 = build_list_cache_key("listings", {"status": "active", "city": "Dubai"}, prefix="p")
        key2 = build_list_cache_key("listings", {"city": "Dubai", "status": "active"}, prefix="p")
        assert key1 == key2

    def test_different_filters_produce_different_keys(self):
        key1 = build_list_cache_key("listings", {"status": "active"}, prefix="p")
        key2 = build_list_cache_key("listings", {"status": "sold"}, prefix="p")
        assert key1 != key2

    def test_kwargs_merged_into_filters(self):
        key1 = build_list_cache_key("listings", {"status": "active"}, prefix="p", page=2)
        key2 = build_list_cache_key("listings", {"status": "active", "page": 2}, prefix="p")
        assert key1 == key2

    def test_key_contains_hash_prefix(self):
        key = build_list_cache_key("listings", {"status": "active"}, prefix="p")
        assert "hash_" in key


class TestInvalidatePattern:
    async def test_deletes_matching_keys_and_returns_count(self):
        cache = MagicMock()
        cache.scan = AsyncMock(return_value=(0, ["p:listings:1", "p:listings:2"]))
        cache.delete = AsyncMock(return_value=2)
        count = await invalidate_pattern(cache, "p:listings:*")
        assert count == 2
        cache.delete.assert_awaited_once_with("p:listings:1", "p:listings:2")

    async def test_handles_multiple_scan_pages(self):
        cache = MagicMock()
        cache.scan = AsyncMock(side_effect=[
            (10, ["key:1"]),   # page 1, cursor != 0
            (0, ["key:2"]),    # page 2, done
        ])
        cache.delete = AsyncMock(return_value=1)
        count = await invalidate_pattern(cache, "key:*")
        assert count == 2

    async def test_returns_zero_when_no_keys_match(self):
        cache = MagicMock()
        cache.scan = AsyncMock(return_value=(0, []))
        count = await invalidate_pattern(cache, "nonexistent:*")
        assert count == 0

    async def test_returns_zero_silently_on_error(self):
        cache = MagicMock()
        cache.scan = AsyncMock(side_effect=Exception("Redis error"))
        count = await invalidate_pattern(cache, "p:*")
        assert count == 0


class TestInvalidateEntityCache:
    async def test_deletes_specific_entity_by_id(self):
        cache = MagicMock()
        cache.delete = AsyncMock(return_value=1)
        result = await invalidate_entity_cache(cache, "listings", "abc-123", prefix="dev:svc")
        assert result == 1
        cache.delete.assert_awaited_once()

    async def test_invalidates_all_entities_when_no_identifier(self):
        cache = MagicMock()
        cache.scan = AsyncMock(return_value=(0, ["dev:svc:listings:1"]))
        cache.delete = AsyncMock(return_value=1)
        await invalidate_entity_cache(cache, "listings", prefix="dev:svc")
        # Should scan+delete, not direct delete
        cache.scan.assert_awaited_once()

    async def test_uses_tenant_scope_in_pattern(self):
        cache = MagicMock()
        cache.scan = AsyncMock(return_value=(0, []))
        cache.delete = AsyncMock(return_value=0)
        await invalidate_entity_cache(cache, "listings", tenant_id="t1", prefix="dev:svc")
        scan_call = cache.scan.call_args
        assert "t1" in str(scan_call)


class TestInvalidateListCaches:
    async def test_deletes_all_list_keys_for_entity(self):
        cache = MagicMock()
        cache.scan = AsyncMock(return_value=(0, ["p:listings:list:all"]))
        cache.delete = AsyncMock(return_value=1)
        count = await invalidate_list_caches(cache, "listings", prefix="p")
        assert count == 1
        scan_call = cache.scan.call_args
        assert "list" in str(scan_call)
