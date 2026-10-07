"""
Async circuit breaker for service-to-service calls. State lives in the process.

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

After ``recovery_timeout`` an open breaker admits exactly one probe. A probe that
never reports within another ``recovery_timeout`` is treated as lost and replaced.
"""

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60,
    ) -> None:
        self.name = name
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._opened_at = 0.0
        self._probe_started_at: float | None = None

    async def is_open(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return False
        now = time.monotonic()
        if self.state == CircuitState.OPEN:
            if now - self._opened_at < self.recovery_timeout:
                return True
            self._transition(CircuitState.HALF_OPEN)
        elif (
            self._probe_started_at is not None
            and now - self._probe_started_at < self.recovery_timeout
        ):
            return True
        self._probe_started_at = now
        return False

    async def record_success(self) -> None:
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self._probe_started_at = None
            self._transition(CircuitState.CLOSED)

    async def record_failure(self) -> None:
        self.failure_count += 1
        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self._opened_at = time.monotonic()
            self._probe_started_at = None
            self._transition(CircuitState.OPEN)

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
