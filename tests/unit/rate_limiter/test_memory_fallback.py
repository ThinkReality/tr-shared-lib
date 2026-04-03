"""Tests for MemoryFallback in-memory rate limiter."""

import time

from tr_shared.rate_limiter.memory_fallback import MemoryFallback


class TestMemoryFallback:
    def _fallback(self, threshold: int = 10_000) -> MemoryFallback:
        return MemoryFallback(cleanup_threshold=threshold)

    async def test_first_request_allowed(self):
        fb = self._fallback()
        result = await fb.check("key:a", limit=5, window_seconds=60)
        assert result.allowed is True

    async def test_remaining_decrements_on_first_request(self):
        fb = self._fallback()
        result = await fb.check("key:a", limit=5, window_seconds=60)
        assert result.remaining == 4

    async def test_count_increments_across_calls(self):
        fb = self._fallback()
        await fb.check("key:b", limit=5, window_seconds=60)
        await fb.check("key:b", limit=5, window_seconds=60)
        result = await fb.check("key:b", limit=5, window_seconds=60)
        assert result.remaining == 2

    async def test_at_limit_is_blocked(self):
        fb = self._fallback()
        for _ in range(3):
            await fb.check("key:c", limit=3, window_seconds=60)
        result = await fb.check("key:c", limit=3, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after > 0

    async def test_different_keys_are_isolated(self):
        fb = self._fallback()
        for _ in range(3):
            await fb.check("key:d", limit=3, window_seconds=60)
        # Different key should be unaffected
        result = await fb.check("key:e", limit=3, window_seconds=60)
        assert result.allowed is True

    async def test_expired_bucket_resets(self):
        fb = self._fallback()
        # Fill up the limit
        for _ in range(3):
            await fb.check("key:f", limit=3, window_seconds=1)
        blocked = await fb.check("key:f", limit=3, window_seconds=1)
        assert blocked.allowed is False

        # Manually expire the bucket
        fb._buckets["key:f"] = {"count": 3, "reset_time": time.time() - 0.1}
        # Next check should start fresh
        result = await fb.check("key:f", limit=3, window_seconds=1)
        assert result.allowed is True

    async def test_reset_at_is_in_the_future(self):
        fb = self._fallback()
        now = int(time.time())
        result = await fb.check("key:g", limit=5, window_seconds=60)
        assert result.reset_at > now

    async def test_reset_at_roughly_window_seconds_away(self):
        fb = self._fallback()
        now = int(time.time())
        result = await fb.check("key:h", limit=5, window_seconds=60)
        # reset_at should be approximately now + 60
        assert now + 55 <= result.reset_at <= now + 65

    async def test_cleanup_removes_expired_buckets(self):
        fb = MemoryFallback(cleanup_threshold=2)
        # Add expired buckets
        for i in range(3):
            fb._buckets[f"old:key:{i}"] = {
                "count": 1,
                "reset_time": time.time() - 100,
            }
        # Trigger cleanup by adding a new check when over threshold
        result = await fb.check("key:new", limit=10, window_seconds=60)
        assert result.allowed is True
        # Expired buckets should be removed; only "key:new" remains
        assert "key:new" in fb._buckets
        assert all(
            "old:key" not in k for k in fb._buckets
        )

    async def test_blocked_retry_after_is_positive(self):
        fb = self._fallback()
        for _ in range(2):
            await fb.check("key:i", limit=2, window_seconds=30)
        result = await fb.check("key:i", limit=2, window_seconds=30)
        assert result.allowed is False
        assert result.retry_after >= 1
