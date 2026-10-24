import asyncio
import uuid

import pytest

from tr_shared.events.consumer import InMemoryIdempotencyChecker

pytestmark = pytest.mark.integration


def _checker(redis_url: str, group: str) -> InMemoryIdempotencyChecker:
    return InMemoryIdempotencyChecker(redis_url=redis_url, group_name=group, ttl_days=1)


async def test_an_event_marked_by_one_instance_is_processed_for_another(redis_url):
    group = f"itest-{uuid.uuid4().hex[:8]}"
    marking, asking = _checker(redis_url, group), _checker(redis_url, group)
    try:
        await marking.mark_processed("evt-1")
        assert await asking.is_processed("evt-1") is True
        assert await asking.is_processed("evt-2") is False
    finally:
        await marking.aclose()
        await asking.aclose()


def test_the_checker_serves_every_event_loop(redis_url):
    group = f"itest-{uuid.uuid4().hex[:8]}"
    marking, asking = _checker(redis_url, group), _checker(redis_url, group)

    try:
        asyncio.run(marking.mark_processed("evt-1"))
        asyncio.run(asking.is_processed("evt-0"))
        asyncio.run(marking.mark_processed("evt-2"))
        processed = asyncio.run(asking.is_processed("evt-2"))
    finally:
        asyncio.run(marking.aclose())
        asyncio.run(asking.aclose())

    assert processed is True
