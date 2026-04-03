"""Tests for the central RateLimiter class."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tr_shared.rate_limiter.core import RateLimiter
from tr_shared.rate_limiter.schemas import (
    Algorithm,
    FailMode,
    RateLimitConfig,
    RateLimitInfo,
    RateLimitResult,
    WindowConfig,
)


def _allowed_result(limit: int = 100, remaining: int = 99) -> RateLimitResult:
    return RateLimitResult(
        allowed=True, limit=limit, remaining=remaining,
        reset_at=int(time.time()) + 60, retry_after=0,
    )


def _blocked_result(limit: int = 100) -> RateLimitResult:
    return RateLimitResult(
        allowed=False, limit=limit, remaining=0,
        reset_at=int(time.time()) + 30, retry_after=30,
    )


class TestBuildKey:
    def test_format_with_prefix(self):
        limiter = RateLimiter(key_prefix="dev:lead")
        key = limiter.build_key(identifier="user123", endpoint="*", scope="default")
        assert key.startswith("dev:lead:rl:default:user123")

    def test_format_without_prefix(self):
        limiter = RateLimiter()
        key = limiter.build_key(identifier="user123", endpoint="*", scope="default")
        assert "rl:default:user123" in key

    def test_endpoint_star_not_normalized(self):
        limiter = RateLimiter(key_prefix="svc")
        key = limiter.build_key(identifier="u1", endpoint="*", scope="api")
        assert key.endswith(":*")

    def test_uuid_in_endpoint_normalized(self):
        limiter = RateLimiter(key_prefix="svc")
        key = limiter.build_key(
            identifier="u1",
            endpoint="/api/v1/listings/123e4567-e89b-12d3-a456-426614174000",
            scope="api",
        )
        assert "{id}" in key
        assert "123e4567" not in key

    def test_scope_in_key(self):
        limiter = RateLimiter(key_prefix="svc")
        key = limiter.build_key(identifier="u1", endpoint="*", scope="webhook")
        assert "webhook" in key

    def test_empty_prefix_no_leading_colon(self):
        limiter = RateLimiter(key_prefix="")
        key = limiter.build_key(identifier="u1", endpoint="*", scope="s")
        assert not key.startswith(":")


class TestLazyRedisConnection:
    async def test_no_connection_on_init(self):
        """Redis client should NOT be created at __init__ time."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            RateLimiter(redis_url="redis://localhost:6379/0")
            mock_from_url.assert_not_called()

    async def test_redis_client_used_directly_when_provided(self):
        mock_redis = AsyncMock()
        mock_redis.eval = AsyncMock(return_value=[1, 0, 59])
        limiter = RateLimiter(redis_client=mock_redis)
        client = await limiter._get_redis()
        assert client is mock_redis


class TestCheck:
    @pytest.fixture
    def limiter_with_mock_redis(self):
        mock_redis = AsyncMock()
        mock_redis.eval = AsyncMock(return_value=[1, 0, 59])
        limiter = RateLimiter(redis_client=mock_redis)
        return limiter, mock_redis

    async def test_returns_rate_limit_info(self, limiter_with_mock_redis):
        limiter, _ = limiter_with_mock_redis
        config = RateLimitConfig(windows=[WindowConfig(limit=100, window_seconds=60)])
        key = limiter.build_key(identifier="u1", endpoint="*", scope="test")
        info = await limiter.check(key=key, config=config)
        assert isinstance(info, RateLimitInfo)

    async def test_allowed_when_under_limit(self, limiter_with_mock_redis):
        limiter, mock_redis = limiter_with_mock_redis
        mock_redis.eval.return_value = [1, 0, 59]  # count=1, not over, ttl=59
        config = RateLimitConfig(windows=[WindowConfig(limit=100, window_seconds=60)])
        key = limiter.build_key(identifier="u1", endpoint="*", scope="test")
        info = await limiter.check(key=key, config=config)
        assert info.is_blocked is False

    async def test_blocked_when_over_limit(self, limiter_with_mock_redis):
        limiter, mock_redis = limiter_with_mock_redis
        mock_redis.eval.return_value = [101, 1, 30]  # count=101, over=True, ttl=30
        config = RateLimitConfig(windows=[WindowConfig(limit=100, window_seconds=60)])
        key = limiter.build_key(identifier="u1", endpoint="*", scope="test")
        info = await limiter.check(key=key, config=config)
        assert info.is_blocked is True

    async def test_multi_window_blocked_if_any_blocked(self, limiter_with_mock_redis):
        limiter, mock_redis = limiter_with_mock_redis
        # First window allowed, second blocked
        mock_redis.eval.side_effect = [
            [1, 0, 59],    # minute window: allowed
            [1001, 1, 30], # hour window: blocked
        ]
        config = RateLimitConfig(
            windows=[
                WindowConfig(limit=100, window_seconds=60),
                WindowConfig(limit=1000, window_seconds=3600),
            ]
        )
        key = limiter.build_key(identifier="u1", endpoint="*", scope="test")
        info = await limiter.check(key=key, config=config)
        assert info.is_blocked is True
        assert len(info.results) == 2

    async def test_redis_failure_fail_open(self):
        """Redis error with FailMode.OPEN should allow the request."""
        mock_redis = AsyncMock()
        mock_redis.eval.side_effect = Exception("Redis connection refused")
        limiter = RateLimiter(redis_client=mock_redis, enable_memory_fallback=False)
        config = RateLimitConfig(fail_mode=FailMode.OPEN)
        info = await limiter.check(key="test:key", config=config)
        assert info.is_blocked is False

    async def test_redis_failure_fail_closed(self):
        """Redis error with FailMode.CLOSED should block the request."""
        mock_redis = AsyncMock()
        mock_redis.eval.side_effect = Exception("Redis connection refused")
        limiter = RateLimiter(redis_client=mock_redis, enable_memory_fallback=False)
        config = RateLimitConfig(fail_mode=FailMode.CLOSED)
        info = await limiter.check(key="test:key", config=config)
        assert info.is_blocked is True

    async def test_memory_fallback_used_when_redis_fails(self):
        """When Redis fails and enable_memory_fallback=True, uses in-memory counter."""
        mock_redis = AsyncMock()
        mock_redis.eval.side_effect = Exception("Redis down")
        limiter = RateLimiter(redis_client=mock_redis, enable_memory_fallback=True)
        config = RateLimitConfig(fail_mode=FailMode.OPEN)
        info = await limiter.check(key="test:key", config=config)
        # Memory fallback allows the request (first call)
        assert info.is_blocked is False


class TestReset:
    async def test_reset_returns_true_when_key_deleted(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)
        limiter = RateLimiter(redis_client=mock_redis)
        config = RateLimitConfig(windows=[WindowConfig(limit=100, window_seconds=60)])
        result = await limiter.reset(key="some:key", config=config)
        assert result is True
        mock_redis.delete.assert_called_once()

    async def test_reset_returns_false_when_key_missing(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=0)
        limiter = RateLimiter(redis_client=mock_redis)
        config = RateLimitConfig(windows=[WindowConfig(limit=100, window_seconds=60)])
        result = await limiter.reset(key="missing:key", config=config)
        assert result is False

    async def test_reset_returns_false_when_no_redis(self):
        limiter = RateLimiter()  # No redis URL or client
        result = await limiter.reset(key="some:key")
        assert result is False


class TestStatus:
    async def test_status_returns_empty_info_when_no_redis(self):
        limiter = RateLimiter()
        info = await limiter.status(key="some:key")
        assert isinstance(info, RateLimitInfo)
        assert info.is_blocked is False

    async def test_status_reads_current_count(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="5")
        mock_redis.ttl = AsyncMock(return_value=45)
        limiter = RateLimiter(redis_client=mock_redis)
        config = RateLimitConfig(windows=[WindowConfig(limit=100, window_seconds=60)])
        info = await limiter.status(key="some:key", config=config)
        assert len(info.results) == 1
        assert info.results[0].limit == 100
