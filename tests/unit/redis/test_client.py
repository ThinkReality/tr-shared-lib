"""Tests for the shared Redis client singleton."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import tr_shared.redis.client as redis_module
from tr_shared.redis.client import close_redis_client, get_redis_client


@pytest.fixture(autouse=True)
def reset_redis_client():
    """Reset the module-level singleton between tests."""
    redis_module._client = None
    yield
    redis_module._client = None


class TestGetRedisClient:
    async def test_returns_client_instance(self):
        with patch("tr_shared.redis.client.aioredis.ConnectionPool.from_url"), \
             patch("tr_shared.redis.client.aioredis.Redis") as mock_redis:
            mock_instance = MagicMock()
            mock_redis.return_value = mock_instance
            result = await get_redis_client("redis://localhost:6379/0")
            assert result is mock_instance

    async def test_creates_pool_with_correct_url(self):
        with patch("tr_shared.redis.client.aioredis.ConnectionPool.from_url") as mock_pool, \
             patch("tr_shared.redis.client.aioredis.Redis"):
            await get_redis_client("redis://localhost:6379/0")
            mock_pool.assert_called_once()
            call_args = mock_pool.call_args
            assert call_args[0][0] == "redis://localhost:6379/0"

    async def test_returns_same_client_on_second_call(self):
        with patch("tr_shared.redis.client.aioredis.ConnectionPool.from_url"), \
             patch("tr_shared.redis.client.aioredis.Redis") as mock_redis:
            mock_instance = MagicMock()
            mock_redis.return_value = mock_instance

            client1 = await get_redis_client("redis://localhost:6379/0")
            client2 = await get_redis_client("redis://localhost:6379/0")
            assert client1 is client2

    async def test_pool_created_only_once(self):
        with patch("tr_shared.redis.client.aioredis.ConnectionPool.from_url") as mock_pool, \
             patch("tr_shared.redis.client.aioredis.Redis"):
            await get_redis_client("redis://localhost:6379/0")
            await get_redis_client("redis://localhost:6379/0")
            mock_pool.assert_called_once()

    async def test_decode_responses_passed_to_pool(self):
        with patch("tr_shared.redis.client.aioredis.ConnectionPool.from_url") as mock_pool, \
             patch("tr_shared.redis.client.aioredis.Redis"):
            await get_redis_client("redis://localhost:6379/0", decode_responses=False)
            call_kwargs = mock_pool.call_args[1]
            assert call_kwargs["decode_responses"] is False


class TestCloseRedisClient:
    async def test_close_sets_client_to_none(self):
        mock_client = AsyncMock()
        mock_client.is_closed = False
        redis_module._client = mock_client

        await close_redis_client()
        assert redis_module._client is None

    async def test_close_calls_aclose(self):
        mock_client = AsyncMock()
        mock_client.is_closed = False
        redis_module._client = mock_client

        await close_redis_client()
        mock_client.aclose.assert_awaited_once()

    async def test_close_when_no_client_is_noop(self):
        redis_module._client = None
        # Should not raise
        await close_redis_client()
