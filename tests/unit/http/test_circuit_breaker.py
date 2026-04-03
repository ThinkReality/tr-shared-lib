"""Tests for CircuitBreaker."""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from tr_shared.http.circuit_breaker import CircuitBreaker, CircuitState


class TestInitialization:
    def test_starts_closed(self):
        cb = CircuitBreaker("svc")
        assert cb.state == CircuitState.CLOSED

    def test_failure_count_starts_zero(self):
        cb = CircuitBreaker("svc")
        assert cb.failure_count == 0

    def test_default_threshold_is_5(self):
        cb = CircuitBreaker("svc")
        assert cb.failure_threshold == 5

    def test_custom_threshold(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        assert cb.failure_threshold == 3


class TestClosedState:
    async def test_is_open_returns_false_when_closed(self):
        cb = CircuitBreaker("svc")
        assert await cb.is_open() is False

    async def test_record_success_resets_failure_count(self):
        cb = CircuitBreaker("svc")
        cb.failure_count = 3
        await cb.record_success()
        assert cb.failure_count == 0

    async def test_failure_below_threshold_stays_closed(self):
        cb = CircuitBreaker("svc", failure_threshold=5)
        for _ in range(4):
            await cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    async def test_failure_at_threshold_opens_breaker(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        for _ in range(3):
            await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    async def test_record_failure_increments_count(self):
        cb = CircuitBreaker("svc", failure_threshold=10)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.failure_count == 2


class TestOpenState:
    async def test_is_open_returns_true_when_open(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert await cb.is_open() is True

    async def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        # Simulate timeout elapsed
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        assert await cb.is_open() is False
        assert cb.state == CircuitState.HALF_OPEN

    async def test_still_open_before_timeout(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=3600)
        await cb.record_failure()
        cb.last_failure_time = datetime.now()
        assert await cb.is_open() is True


class TestHalfOpenState:
    async def test_first_probe_allowed(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        # First call: transitions to half-open and allows
        is_open = await cb.is_open()
        assert is_open is False
        assert cb.state == CircuitState.HALF_OPEN

    async def test_concurrent_probes_rejected(self):
        """While a probe is in flight, subsequent calls should be rejected."""
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        # First call: transitions to HALF_OPEN, probe_in_flight=False, allows
        await cb.is_open()
        # Second call: sets probe_in_flight=True, allows (this is the probe)
        await cb.is_open()
        # Third call: probe_in_flight=True → rejected
        assert await cb.is_open() is True

    async def test_success_in_half_open_closes_breaker(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        await cb.is_open()  # transition to half-open
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED

    async def test_failure_in_half_open_reopens_breaker(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        await cb.is_open()  # transition to half-open
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestTransition:
    async def test_state_changes_are_logged(self):
        """_transition should not raise; it logs state changes."""
        cb = CircuitBreaker("svc", failure_threshold=1)
        await cb.record_failure()  # triggers _transition to OPEN
        assert cb.state == CircuitState.OPEN

    def test_same_state_transition_is_noop(self):
        cb = CircuitBreaker("svc")
        old_state = cb.state
        cb._transition(CircuitState.CLOSED)  # already CLOSED
        assert cb.state == old_state


def _mock_redis(state_data: dict | None = None):
    """Return an AsyncMock Redis client, optionally pre-populated with state."""
    r = AsyncMock()
    r.hgetall = AsyncMock(return_value=state_data or {})
    r.hset = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=1)
    return r


class TestRedisStatePersistence:
    async def test_open_state_loaded_from_redis_on_first_is_open(self):
        """If Redis has state=open with a recent failure, the breaker starts OPEN."""
        # Use a fresh timestamp so the recovery timeout hasn't elapsed
        recent_ts = str(time.time())
        redis = _mock_redis({"state": "open", "failure_count": "5", "last_failure_time": recent_ts})
        cb = CircuitBreaker("svc", failure_threshold=10, recovery_timeout=9999, redis_client=redis)
        result = await cb.is_open()
        assert result is True
        assert cb.state == CircuitState.OPEN

    async def test_state_saved_to_redis_on_failure(self):
        """record_failure() persists updated state to Redis."""
        redis = _mock_redis()
        cb = CircuitBreaker("svc", failure_threshold=3, redis_client=redis)
        await cb.record_failure()
        redis.hset.assert_awaited_once()
        saved = redis.hset.call_args.kwargs.get("mapping") or redis.hset.call_args[1].get("mapping")
        assert saved["failure_count"] == "1"

    async def test_state_saved_to_redis_on_success(self):
        """record_success() from HALF_OPEN persists closed state to Redis."""
        redis = _mock_redis()
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1, redis_client=redis)
        await cb.record_failure()  # → OPEN
        # Simulate recovery timeout so is_open() transitions to HALF_OPEN
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        await cb.is_open()         # → HALF_OPEN
        redis.hset.reset_mock()
        await cb.record_success()  # HALF_OPEN → CLOSED
        redis.hset.assert_awaited_once()
        saved = redis.hset.call_args.kwargs.get("mapping") or redis.hset.call_args[1].get("mapping")
        assert saved["state"] == "closed"

    async def test_redis_load_error_falls_back_to_memory_state(self):
        """If Redis raises on load, the breaker stays in memory CLOSED state."""
        redis = _mock_redis()
        redis.hgetall.side_effect = ConnectionError("Redis down")
        cb = CircuitBreaker("svc", failure_threshold=5, redis_client=redis)
        result = await cb.is_open()
        assert result is False            # still CLOSED (memory default)
        assert cb.state == CircuitState.CLOSED

    async def test_redis_save_error_does_not_raise(self):
        """If Redis raises on save, the breaker still works in-memory."""
        redis = _mock_redis()
        redis.hset.side_effect = ConnectionError("Redis down")
        cb = CircuitBreaker("svc", failure_threshold=1, redis_client=redis)
        await cb.record_failure()  # Must not raise
        assert cb.state == CircuitState.OPEN

    async def test_state_loaded_only_once(self):
        """hgetall is called exactly once regardless of how many times is_open() is called."""
        redis = _mock_redis()
        cb = CircuitBreaker("svc", redis_client=redis)
        await cb.is_open()
        await cb.is_open()
        await cb.is_open()
        redis.hgetall.assert_awaited_once()

    async def test_no_redis_uses_memory_only(self):
        """Without a redis_client, behaviour is unchanged from before."""
        cb = CircuitBreaker("svc", failure_threshold=1)
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN  # works normally, no Redis calls
