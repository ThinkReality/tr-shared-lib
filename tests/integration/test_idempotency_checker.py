import asyncio
import os
import uuid

import pytest

from tr_shared.events.consumer import InMemoryIdempotencyChecker

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)


def _checker(group: str) -> InMemoryIdempotencyChecker:
    assert TEST_REDIS_URL is not None
    return InMemoryIdempotencyChecker(redis_url=TEST_REDIS_URL, group_name=group, ttl_days=1)


async def test_an_event_marked_by_one_instance_is_processed_for_another():
    group = f"itest-{uuid.uuid4().hex[:8]}"
    marking, asking = _checker(group), _checker(group)
    try:
        await marking.mark_processed("evt-1")
        assert await asking.is_processed("evt-1") is True
        assert await asking.is_processed("evt-2") is False
    finally:
        await marking.aclose()
        await asking.aclose()


def test_the_checker_serves_every_event_loop():
    group = f"itest-{uuid.uuid4().hex[:8]}"
    marking, asking = _checker(group), _checker(group)

    try:
        asyncio.run(marking.mark_processed("evt-1"))
        asyncio.run(asking.is_processed("evt-0"))
        asyncio.run(marking.mark_processed("evt-2"))
        processed = asyncio.run(asking.is_processed("evt-2"))
    finally:
        asyncio.run(marking.aclose())
        asyncio.run(asking.aclose())

    assert processed is True
