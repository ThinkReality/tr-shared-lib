"""Tests for RetryStateStore (fakeredis-backed)."""

import pytest

from tr_shared.events.retry_state import RetryStateStore


@pytest.fixture
def store(async_fake_redis):
    return RetryStateStore(async_fake_redis, "test_stream", "test_group")


class TestRetryStateStore:
    async def test_increment_counts_up_from_one(self, store):
        assert await store.increment("msg-1") == 1
        assert await store.increment("msg-1") == 2
        assert await store.increment("msg-1") == 3

    async def test_increment_is_per_message(self, store):
        assert await store.increment("msg-a") == 1
        assert await store.increment("msg-b") == 1
        assert await store.increment("msg-a") == 2

    async def test_get_unknown_is_zero(self, store):
        assert await store.get("never-seen") == 0

    async def test_get_reflects_increments(self, store):
        await store.increment("msg-1")
        await store.increment("msg-1")
        assert await store.get("msg-1") == 2

    async def test_clear_resets_counter(self, store):
        await store.increment("msg-1")
        await store.clear("msg-1")
        assert await store.get("msg-1") == 0
        assert await store.increment("msg-1") == 1

    async def test_ttl_refreshed_on_increment(self, async_fake_redis, store):
        await store.increment("msg-1")
        ttl = await async_fake_redis.ttl("test_stream:test_group:retries")
        assert ttl > 0

    async def test_key_is_scoped_to_stream_and_group(self, async_fake_redis):
        a = RetryStateStore(async_fake_redis, "stream_a", "group_1")
        b = RetryStateStore(async_fake_redis, "stream_b", "group_1")
        await a.increment("msg-1")
        assert await b.get("msg-1") == 0
