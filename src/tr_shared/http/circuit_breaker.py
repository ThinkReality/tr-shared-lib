"""
Async circuit breaker for service-to-service calls.

Extracted from TR-HR-System-be (async, with metrics) and crm-backend
(state transition logging). Combined into the single best pattern.

Usage::

    breaker = CircuitBreaker(name="crm-backend", failure_threshold=5)

    if await breaker.is_open():
        raise CircuitBreakerOpenError("crm-backend")

    try:
        result = await call_service()
        await breaker.record_success()
    except Exception:
        await breaker.record_failure()
        raise
"""

import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Async circuit breaker with configurable thresholds.

    Args:
        name: Identifier for logging/metrics.
        failure_threshold: Consecutive failures before opening.
        recovery_timeout: Seconds to wait before probing (half-open).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        redis_client: Any = None,
        state_ttl: int | None = None,
    ) -> None:
        self.name = name
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time: datetime | None = None
        self._half_open_probe_in_flight = False
        self._lock = asyncio.Lock()
        # Optional Redis persistence — shared state across restarts and instances
        self._redis = redis_client
        self._redis_key = f"circuit_breaker:{name}"
        self._state_ttl = state_ttl or (recovery_timeout * 10)
        self._state_loaded = False

    async def _load_state(self) -> None:
        """Load persisted state from Redis (called once on first access)."""
        if self._redis is None:
            return
        try:
            data = await self._redis.hgetall(self._redis_key)
            if data:
                self.state = CircuitState(data.get("state", CircuitState.CLOSED.value))
                self.failure_count = int(data.get("failure_count", 0))
                lft = data.get("last_failure_time")
                if lft:
                    self.last_failure_time = datetime.fromtimestamp(float(lft))
        except Exception:
            logger.warning(
                "CircuitBreaker: failed to load state from Redis for %s", self.name
            )

    async def _save_state(self) -> None:
        """Persist current state to Redis."""
        if self._redis is None:
            return
        try:
            await self._redis.hset(
                self._redis_key,
                mapping={
                    "state": self.state.value,
                    "failure_count": str(self.failure_count),
                    "last_failure_time": (
                        str(self.last_failure_time.timestamp())
                        if self.last_failure_time
                        else ""
                    ),
                },
            )
            await self._redis.expire(self._redis_key, self._state_ttl)
        except Exception:
            logger.warning(
                "CircuitBreaker: failed to save state to Redis for %s", self.name
            )

    async def is_open(self) -> bool:
        """Return True if requests should be rejected (circuit open)."""
        async with self._lock:
            if not self._state_loaded:
                await self._load_state()
                self._state_loaded = True
            if self.state == CircuitState.OPEN:
                if self.last_failure_time is None:
                    return True
                elapsed = datetime.now() - self.last_failure_time
                if elapsed > timedelta(seconds=self.recovery_timeout):
                    self._transition(CircuitState.HALF_OPEN)
                    self._half_open_probe_in_flight = False
                    await self._save_state()
                    return False
                return True
            elif self.state == CircuitState.HALF_OPEN:
                if self._half_open_probe_in_flight:
                    return True
                self._half_open_probe_in_flight = True
                return False
            return False

    async def record_success(self) -> None:
        """Record a successful call — resets failure count."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.CLOSED)
                self._half_open_probe_in_flight = False
            self.failure_count = 0
            await self._save_state()

    async def record_failure(self) -> None:
        """Record a failed call — may trip the breaker open."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()

            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
                self._half_open_probe_in_flight = False
            elif self.failure_count >= self.failure_threshold:
                self._transition(CircuitState.OPEN)
            await self._save_state()

    def _transition(self, new_state: CircuitState) -> None:
        old_state = self.state
        if old_state == new_state:
            return
        self.state = new_state
        log_level = logging.WARNING if new_state == CircuitState.OPEN else logging.INFO
        logger.log(
            log_level,
            "circuit_breaker_state_transition",
            extra={
                "circuit_breaker": self.name,
                "from_state": old_state.value,
                "to_state": new_state.value,
                "failure_count": self.failure_count,
            },
        )
