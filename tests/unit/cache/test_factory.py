"""Tests for CacheProviderFactory."""

import pytest

from tr_shared.cache.factory import CacheProvider, CacheProviderFactory


class TestCacheProviderFactory:
    def test_create_standard_returns_standard_redis_adapter(self):
        from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
        adapter = CacheProviderFactory.create("standard", redis_url="redis://localhost:6379/0")
        assert isinstance(adapter, StandardRedisAdapter)

    def test_create_upstash_returns_upstash_adapter(self):
        pytest.importorskip("upstash_redis", reason="upstash-redis extra not installed")
        from tr_shared.cache.adapters.upstash import UpstashAdapter
        adapter = CacheProviderFactory.create(
            "upstash",
            upstash_rest_url="https://example.upstash.io",
            upstash_rest_token="token-123",
        )
        assert isinstance(adapter, UpstashAdapter)

    def test_create_invalid_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported cache provider"):
            CacheProviderFactory.create("invalid_provider")

    def test_create_case_insensitive(self):
        from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
        adapter = CacheProviderFactory.create("STANDARD", redis_url="redis://localhost:6379/0")
        assert isinstance(adapter, StandardRedisAdapter)

    async def test_create_and_initialize_calls_initialize(self):
        from unittest.mock import AsyncMock, patch
        mock_adapter = AsyncMock()
        mock_adapter.initialize = AsyncMock(return_value=True)
        with patch.object(CacheProviderFactory, "create", return_value=mock_adapter):
            result = await CacheProviderFactory.create_and_initialize(provider="standard")
            mock_adapter.initialize.assert_awaited_once()
            assert result is mock_adapter


class TestCacheProviderEnum:
    def test_standard_value(self):
        assert CacheProvider.STANDARD == "standard"

    def test_upstash_value(self):
        assert CacheProvider.UPSTASH == "upstash"
