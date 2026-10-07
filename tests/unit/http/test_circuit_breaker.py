import asyncio
import inspect

import pytest

from tr_shared.http.circuit_breaker import CircuitBreaker, CircuitState

RECOVERY = 0.05


async def _opened(threshold: int = 1, recovery: float = RECOVERY) -> CircuitBreaker:
    breaker = CircuitBreaker("svc", failure_threshold=threshold, recovery_timeout=recovery)
    for _ in range(threshold):
        await breaker.record_failure()
    return breaker


async def _half_open() -> CircuitBreaker:
    breaker = await _opened()
    await asyncio.sleep(RECOVERY * 1.5)
    assert await breaker.is_open() is False
    assert breaker.state == CircuitState.HALF_OPEN
    return breaker


async def test_a_new_breaker_is_closed_and_admits_calls():
    breaker = CircuitBreaker("svc")

    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    assert await breaker.is_open() is False


async def test_failures_below_the_threshold_keep_it_closed():
    breaker = CircuitBreaker("svc", failure_threshold=3)
    await breaker.record_failure()
    await breaker.record_failure()

    assert breaker.state == CircuitState.CLOSED
    assert await breaker.is_open() is False


async def test_a_success_resets_the_failure_count():
    breaker = CircuitBreaker("svc", failure_threshold=3)
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.record_success()
    await breaker.record_failure()

    assert breaker.failure_count == 1
    assert breaker.state == CircuitState.CLOSED


async def test_the_threshold_opens_it_and_it_refuses_until_recovery():
    breaker = await _opened(threshold=3, recovery=60)

    assert breaker.state == CircuitState.OPEN
    assert await breaker.is_open() is True


async def test_exactly_one_probe_is_admitted_when_recovery_elapses():
    breaker = await _half_open()

    assert await breaker.is_open() is True
    assert await breaker.is_open() is True


async def test_a_successful_probe_closes_it():
    breaker = await _half_open()
    await breaker.record_success()

    assert breaker.state == CircuitState.CLOSED
    assert await breaker.is_open() is False
    assert await breaker.is_open() is False


async def test_a_failed_probe_reopens_it_for_a_full_recovery_window():
    breaker = await _half_open()
    await breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    assert await breaker.is_open() is True


async def test_a_failed_probe_reopens_it_even_after_a_late_success_reset_the_count():
    breaker = await _opened(threshold=3)
    await breaker.record_success()
    await asyncio.sleep(RECOVERY * 1.5)
    assert await breaker.is_open() is False

    await breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    assert await breaker.is_open() is True


async def test_a_probe_that_never_reports_is_replaced_after_the_recovery_window():
    breaker = await _half_open()
    assert await breaker.is_open() is True

    await asyncio.sleep(RECOVERY * 1.5)

    assert await breaker.is_open() is False
    assert await breaker.is_open() is True
    await breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


async def test_a_reported_probe_is_not_replaced():
    breaker = await _half_open()
    await breaker.record_failure()
    await asyncio.sleep(RECOVERY * 0.5)

    assert await breaker.is_open() is True


async def test_a_zero_recovery_window_admits_a_probe_at_once():
    breaker = await _opened(recovery=0)

    assert await breaker.is_open() is False
    await breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.parametrize("argument", ["redis_client", "state_ttl"])
def test_state_lives_in_the_process_only(argument):
    assert argument not in inspect.signature(CircuitBreaker).parameters
