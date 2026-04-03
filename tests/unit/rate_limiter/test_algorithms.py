"""Tests for FixedWindowAlgorithm and SlidingWindowAlgorithm.

Uses async fakeredis with lupa Lua scripting support to verify the actual
Lua scripts behave correctly.
"""

import time

import pytest

from tr_shared.rate_limiter.algorithms import FixedWindowAlgorithm, SlidingWindowAlgorithm


class TestFixedWindowAlgorithm:
    """Tests for the INCR+EXPIRE fixed-window algorithm."""

    @pytest.fixture
    def algo(self):
        return FixedWindowAlgorithm()

    async def test_first_request_is_allowed(self, algo, async_fake_redis):
        result = await algo.check(async_fake_redis, "fw:test1", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.limit == 5

    async def test_remaining_decrements(self, algo, async_fake_redis):
        result = await algo.check(async_fake_redis, "fw:test2", limit=5, window_seconds=60)
        assert result.remaining == 4

    async def test_count_increments_across_calls(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "fw:test3", limit=10, window_seconds=60)
        result = await algo.check(async_fake_redis, "fw:test3", limit=10, window_seconds=60)
        assert result.remaining == 6

    async def test_at_limit_is_blocked(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "fw:test4", limit=3, window_seconds=60)
        result = await algo.check(async_fake_redis, "fw:test4", limit=3, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0

    async def test_blocked_has_positive_retry_after(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "fw:test5", limit=3, window_seconds=60)
        result = await algo.check(async_fake_redis, "fw:test5", limit=3, window_seconds=60)
        assert result.retry_after >= 1

    async def test_reset_at_is_future_timestamp(self, algo, async_fake_redis):
        now = int(time.time())
        result = await algo.check(async_fake_redis, "fw:test6", limit=5, window_seconds=60)
        assert result.reset_at > now

    async def test_different_keys_are_independent(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "fw:key_a", limit=3, window_seconds=60)
        result = await algo.check(async_fake_redis, "fw:key_b", limit=3, window_seconds=60)
        assert result.allowed is True


class TestSlidingWindowAlgorithm:
    """Tests for the ZSET-based sliding-window algorithm."""

    @pytest.fixture
    def algo(self):
        return SlidingWindowAlgorithm()

    async def test_first_request_is_allowed(self, algo, async_fake_redis):
        result = await algo.check(async_fake_redis, "sw:test1", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.limit == 5

    async def test_remaining_decrements(self, algo, async_fake_redis):
        result = await algo.check(async_fake_redis, "sw:test2", limit=5, window_seconds=60)
        assert result.remaining == 4

    async def test_count_increments_across_calls(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "sw:test3", limit=10, window_seconds=60)
        result = await algo.check(async_fake_redis, "sw:test3", limit=10, window_seconds=60)
        assert result.remaining == 6

    async def test_at_limit_is_blocked(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "sw:test4", limit=3, window_seconds=60)
        result = await algo.check(async_fake_redis, "sw:test4", limit=3, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0

    async def test_blocked_has_retry_after(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "sw:test5", limit=3, window_seconds=60)
        result = await algo.check(async_fake_redis, "sw:test5", limit=3, window_seconds=60)
        assert result.retry_after > 0

    async def test_reset_at_is_future_timestamp(self, algo, async_fake_redis):
        now = int(time.time())
        result = await algo.check(async_fake_redis, "sw:test6", limit=5, window_seconds=60)
        assert result.reset_at > now

    async def test_different_keys_are_independent(self, algo, async_fake_redis):
        for _ in range(3):
            await algo.check(async_fake_redis, "sw:key_a", limit=3, window_seconds=60)
        result = await algo.check(async_fake_redis, "sw:key_b", limit=3, window_seconds=60)
        assert result.allowed is True
