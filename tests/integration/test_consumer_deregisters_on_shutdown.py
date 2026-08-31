"""A cleanly-stopped consumer deregisters itself; one holding pending entries does not.

`EventConsumer.stop()` issued no `XGROUP DELCONSUMER`, and `_sweep_zombie_consumers()`
runs only from `connect()` with a 24h idle floor — so every stopped consumer stayed in
`XINFO CONSUMERS` forever. Any health probe counting `consumers > 0` therefore reported
a group with no live process as running.

**Why deregistration cannot live in `stop()`.** `stop()` is called from a signal
handler while `_claimer_loop` is still in flight, and it closes the shared client. A
`DELCONSUMER` there would race the claimer *and* have no client left to issue itself on.
It belongs in `start()`'s `finally`, after the claimer task has been cancelled and
awaited and `_consume_loop` has returned.

**Why the empty-PEL check is not a TOCTOU.** The lib uses `XAUTOCLAIM` exclusively —
there is no `xclaim` call anywhere in it or in any consuming service — and `XAUTOCLAIM`
assigns entries to the *calling* consumer. So a sibling replica can only move entries
*out of* ours, never in. Once both of our loops are down the PEL can only shrink, and
"empty now" stays true.

Deleting a consumer that still holds pending entries would strand them: `XAUTOCLAIM`
walks the group PEL, so they remain claimable, but the count and ownership records that
ops reads to notice the backlog disappear with it.
"""

import asyncio
import json
import os
import uuid

import pytest
import redis.asyncio as redis

from tr_shared.events.consumer import EventConsumer

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
    name = f"itest:{uuid.uuid4().hex}"
    yield name
    await real_redis.delete(name)


def _build(stream: str, name: str, **kwargs) -> EventConsumer:
    return EventConsumer(
        redis_url=TEST_REDIS_URL,
        stream_name=stream,
        consumer_group=GROUP,
        consumer_name=name,
        block_ms=50,
        claimer_poll_interval=0.05,
        **kwargs,
    )


async def _names(real_redis, stream) -> set[str]:
    try:
        consumers = await real_redis.xinfo_consumers(stream, GROUP)
    except redis.ResponseError:
        return set()
    return {c["name"] for c in consumers}


async def _run_briefly(consumer: EventConsumer, seconds: float = 0.4) -> None:
    task = asyncio.create_task(consumer.start())
    await asyncio.sleep(seconds)
    await consumer.stop()
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_clean_shutdown_deregisters_the_consumer(real_redis, stream):
    consumer = _build(stream, "worker-clean")

    await _run_briefly(consumer)

    assert "worker-clean" not in await _names(real_redis, stream), (
        "a cleanly stopped consumer stayed registered, so `consumers > 0` keeps "
        "reporting a group with no live process as running"
    )


@pytest.mark.asyncio
async def test_a_consumer_holding_pending_entries_stays_registered(real_redis, stream):
    """Its PEL is what the claimer and ops both read; deleting it hides the backlog.

    The pending entry is planted with a raw XREADGROUP rather than by letting a handler
    fail — a failing handler hits the retry policy and the DLQ moves and acks the entry,
    leaving nothing pending. The claim floor is set high so the consumer's own claimer
    cannot reclaim and drain it during the run.
    """
    await real_redis.xgroup_create(stream, GROUP, id="0", mkstream=True)
    await real_redis.xadd(stream, _envelope())
    await real_redis.xreadgroup(
        groupname=GROUP, consumername="worker-pending", streams={stream: ">"}, count=1
    )
    assert (await real_redis.xpending(stream, GROUP))["pending"] == 1

    await _run_briefly(_build(stream, "worker-pending", claim_min_idle_ms=600_000))

    assert (await real_redis.xpending(stream, GROUP))["pending"] == 1
    assert "worker-pending" in await _names(real_redis, stream)


@pytest.mark.asyncio
async def test_no_pel_entry_is_lost_while_a_sibling_claims_concurrently(real_redis, stream):
    """The failure mode this whole task exists to avoid is silent event loss, so the
    shutdown is run against a sibling actively reclaiming from the same group."""
    handled: list[str] = []

    async def _ok(event):
        handled.append(event.event_id)

    leaver = _build(stream, "worker-leaving", claim_min_idle_ms=0)
    sibling = _build(stream, "worker-sibling", claim_min_idle_ms=0)
    for c in (leaver, sibling):
        c.register_handler("user.created", _ok)

    leaver_task = asyncio.create_task(leaver.start())
    sibling_task = asyncio.create_task(sibling.start())
    await asyncio.sleep(0.2)

    envelopes = [_envelope() for _ in range(10)]
    published = {e["event_id"] for e in envelopes}
    for envelope in envelopes:
        await real_redis.xadd(stream, envelope)
    await asyncio.sleep(0.4)

    await leaver.stop()
    await asyncio.wait_for(leaver_task, timeout=5)
    await asyncio.sleep(0.4)

    await sibling.stop()
    await asyncio.wait_for(sibling_task, timeout=5)

    pending = await real_redis.xpending(stream, GROUP)
    # Compared as SETS. With claim_min_idle_ms=0 the sibling reclaims entries that are
    # merely in flight, so duplicates are expected and are not the failure being
    # guarded here — a missing id is.
    assert set(handled) >= published, f"lost across shutdown: {sorted(published - set(handled))}"
    assert pending["pending"] == 0, "entries were stranded in the PEL"


@pytest.mark.asyncio
async def test_deregistration_failure_never_blocks_shutdown(real_redis, stream, monkeypatch):
    """Shutdown must complete even if Redis rejects the DELCONSUMER."""
    consumer = _build(stream, "worker-degraded")

    original = redis.Redis.xgroup_delconsumer

    async def _boom(self, *args, **kwargs):
        raise redis.ResponseError("NOGROUP")

    monkeypatch.setattr(redis.Redis, "xgroup_delconsumer", _boom)
    try:
        await _run_briefly(consumer)
    finally:
        monkeypatch.setattr(redis.Redis, "xgroup_delconsumer", original)
