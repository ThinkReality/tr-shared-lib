"""Integration tests for the PEL-based EventConsumer retry/recovery path,
against a REAL Redis (validates XAUTOCLAIM/PEL semantics the fakeredis unit
tests only emulate).

Runs only when ``TEST_REDIS_URL`` is set — e.g. locally against the dev
``tr-redis-central`` container:

    TEST_REDIS_URL='redis://:devpassword@localhost:6382/15' uv run pytest -m integration

CI provides an ephemeral ``redis:7-alpine`` service and sets the same env.
"""

import json
import os
import uuid

import pytest
import redis.asyncio as redis
from unittest.mock import AsyncMock

from tr_shared.events.consumer import EventConsumer
from tr_shared.events.dead_letter import DeadLetterHandler, dead_letter_stream_name
from tr_shared.events.retry_policy import RetryPolicy
from tr_shared.events.retry_state import RetryStateStore

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)

GROUP = "g"


def _envelope(event_type: str = "user.created") -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "version": "1",
        "tenant_id": "tenant-abc",
        "timestamp": "2026-01-01T00:00:00",
        "source_service": "crm",
        "actor_id": "user-1",
        "data": json.dumps({"name": "Alice"}),
        "metadata": json.dumps({}),
    }


@pytest.fixture
async def real_redis():
    client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def stream(real_redis):
    """A unique stream+group per test (shared Redis DB); torn down after."""
    name = f"itest:{uuid.uuid4().hex}"
    yield name
    for key in (name, dead_letter_stream_name(name), f"{name}:{GROUP}:retries"):
        await real_redis.delete(key)


async def _consumer(real_redis, stream, *, max_retries=3, claim_min_idle_ms=0):
    c = EventConsumer(
        redis_url=TEST_REDIS_URL,
        stream_name=stream,
        consumer_group=GROUP,
        consumer_name="c1",
        retry_policy=RetryPolicy(max_retries=max_retries),
        claim_min_idle_ms=claim_min_idle_ms,
    )
    c._redis = real_redis
    c._dlq = DeadLetterHandler(real_redis, stream, GROUP)
    c._retry_state = RetryStateStore(real_redis, stream, GROUP)
    await c._ensure_consumer_group()
    return c


async def _read_and_process(consumer, real_redis, stream, consumer_name="c1"):
    msgs = await real_redis.xreadgroup(
        groupname=GROUP, consumername=consumer_name, streams={stream: ">"}, count=10
    )
    for _s, entries in msgs or []:
        for msg_id, data in entries:
            _ok, should_ack = await consumer._process_message(msg_id, data)
            if should_ack:
                await consumer._ack(msg_id)


class TestPelRetryRealRedis:
    async def test_retry_recovers_via_claimer_no_xadd(self, real_redis, stream):
        consumer = await _consumer(real_redis, stream)
        handler = AsyncMock(side_effect=[Exception("boom"), None])
        consumer.register_handler("user.created", handler)
        await real_redis.xadd(stream, _envelope())

        await _read_and_process(consumer, real_redis, stream)   # attempt 1 → PEL
        claimed = await consumer._claim_once()                  # attempt 2 → ok

        assert claimed == 1
        assert handler.await_count == 2
        assert (await real_redis.xpending(stream, GROUP))["pending"] == 0
        assert await real_redis.xlen(stream) == 1               # no XADD storm

    async def test_crash_orphan_recovered_from_dead_consumer(self, real_redis, stream):
        consumer = await _consumer(real_redis, stream)
        handler = AsyncMock()
        consumer.register_handler("user.created", handler)
        await real_redis.xadd(stream, _envelope())

        # dead consumer reads, never acks (crash between read and ack)
        await real_redis.xreadgroup(
            groupname=GROUP, consumername="dead", streams={stream: ">"}, count=10
        )
        assert (await real_redis.xpending(stream, GROUP))["pending"] == 1

        claimed = await consumer._claim_once()

        assert claimed == 1
        handler.assert_awaited_once()
        assert (await real_redis.xpending(stream, GROUP))["pending"] == 0

    async def test_max_retries_to_dlq(self, real_redis, stream):
        consumer = await _consumer(real_redis, stream, max_retries=1)
        consumer.register_handler("user.created", AsyncMock(side_effect=Exception("always")))
        await real_redis.xadd(stream, _envelope())

        await _read_and_process(consumer, real_redis, stream)

        assert (await real_redis.xpending(stream, GROUP))["pending"] == 0
        assert await real_redis.xlen(dead_letter_stream_name(stream)) == 1

    async def test_sweep_removes_empty_idle_zombie(self, real_redis, stream):
        consumer = await _consumer(real_redis, stream)
        consumer._zombie_idle_ms = 0
        await real_redis.xgroup_createconsumer(stream, GROUP, "zombie")
        await real_redis.xadd(stream, _envelope())
        await real_redis.xreadgroup(
            groupname=GROUP, consumername="busy", streams={stream: ">"}, count=10
        )

        await consumer._sweep_zombie_consumers()

        names = {c["name"] for c in await real_redis.xinfo_consumers(stream, GROUP)}
        assert "zombie" not in names
        assert "busy" in names
