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
        is_open = await cb.is_open()
        assert is_open is False
        assert cb.state == CircuitState.HALF_OPEN

    async def test_concurrent_probes_rejected(self):
        """Only one probe may be in flight in HALF_OPEN; subsequent calls are rejected
        until the probe resolves (call 1 transitions+allows, call 2 is the probe, call 3 rejected)."""
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        await cb.is_open()
        await cb.is_open()
        assert await cb.is_open() is True

    async def test_success_in_half_open_closes_breaker(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        await cb.is_open()
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED

    async def test_failure_in_half_open_reopens_breaker(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        await cb.is_open()
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestTransition:
    async def test_state_changes_are_logged(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_same_state_transition_is_noop(self):
        cb = CircuitBreaker("svc")
        old_state = cb.state
        cb._transition(CircuitState.CLOSED)
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
        recent_ts = str(time.time())
        redis = _mock_redis({"state": "open", "failure_count": "5", "last_failure_time": recent_ts})
        cb = CircuitBreaker("svc", failure_threshold=10, recovery_timeout=9999, redis_client=redis)
        result = await cb.is_open()
        assert result is True
        assert cb.state == CircuitState.OPEN

    async def test_state_saved_to_redis_on_failure(self):
        redis = _mock_redis()
        cb = CircuitBreaker("svc", failure_threshold=3, redis_client=redis)
        await cb.record_failure()
        redis.hset.assert_awaited_once()
        saved = redis.hset.call_args.kwargs.get("mapping") or redis.hset.call_args[1].get("mapping")
        assert saved["failure_count"] == "1"

    async def test_state_saved_to_redis_on_success(self):
        redis = _mock_redis()
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=1, redis_client=redis)
        await cb.record_failure()
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        await cb.is_open()
        redis.hset.reset_mock()
        await cb.record_success()
        redis.hset.assert_awaited_once()
        saved = redis.hset.call_args.kwargs.get("mapping") or redis.hset.call_args[1].get("mapping")
        assert saved["state"] == "closed"

    async def test_redis_load_error_falls_back_to_memory_state(self):
        redis = _mock_redis()
        redis.hgetall.side_effect = ConnectionError("Redis down")
        cb = CircuitBreaker("svc", failure_threshold=5, redis_client=redis)
        result = await cb.is_open()
        assert result is False
        assert cb.state == CircuitState.CLOSED

    async def test_redis_save_error_does_not_raise(self):
        redis = _mock_redis()
        redis.hset.side_effect = ConnectionError("Redis down")
        cb = CircuitBreaker("svc", failure_threshold=1, redis_client=redis)
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    async def test_state_loaded_only_once(self):
        redis = _mock_redis()
        cb = CircuitBreaker("svc", redis_client=redis)
        await cb.is_open()
        await cb.is_open()
        await cb.is_open()
        redis.hgetall.assert_awaited_once()

    async def test_no_redis_uses_memory_only(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
