"""Each test here pins one way the hand-rolled version read Redis wrong."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import RedisError

from tr_shared.events.group_health import consumer_group_health

STREAM = "tr_event_bus"
GROUP = "activity_consumer_group"
BLOCK_MS = 5000
# consumer_group_health uses block_ms * 3, so the live/dead boundary is 15000ms.


def _client(groups=None, consumers=None, groups_exc=None, consumers_exc=None) -> MagicMock:
    client = MagicMock()
    client.xinfo_groups = AsyncMock(side_effect=groups_exc, return_value=groups or [])
    client.xinfo_consumers = AsyncMock(side_effect=consumers_exc, return_value=consumers or [])
    return client


def _group(**overrides) -> dict:
    return {
        "name": GROUP,
        "consumers": 1,
        "pending": 0,
        "last-delivered-id": "1-0",
        "entries-read": 5,
        "lag": 0,
        **overrides,
    }


def _consumer(name="worker-1", pending=0, idle=100, inactive=-1) -> dict:
    return {"name": name, "pending": pending, "idle": idle, "inactive": inactive}


@pytest.mark.asyncio
class TestLagIsNeverCoerced:
    async def test_nil_lag_is_reported_as_none_not_zero(self):
        """Redis reports `lag` as *present and nil* whenever it cannot reconcile
        entries-read. `int(group.get("lag", 0))` raises TypeError there — the `.get`
        default never fires, because the key is present."""
        client = _client(groups=[_group(lag=None)], consumers=[_consumer()])

        health = await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)

        assert health["lag"] is None
        assert health["exists"] is True
        assert health["error"] is None

    async def test_zero_lag_stays_zero(self):
        """Unknown and caught-up are different answers and must not collapse."""
        client = _client(groups=[_group(lag=0)], consumers=[_consumer()])

        assert (await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS))["lag"] == 0

    async def test_missing_lag_key_is_none(self):
        """Redis < 7.0 does not report lag at all."""
        record = _group()
        del record["lag"]
        client = _client(groups=[record], consumers=[_consumer()])

        assert (await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS))[
            "lag"
        ] is None


@pytest.mark.asyncio
class TestLivenessComesFromIdle:
    async def test_a_dead_consumer_still_registered_is_not_counted_live(self):
        """`consumers > 0` counts registrations. stop() issues no XGROUP DELCONSUMER
        and the startup sweep only removes consumers idle past 24h, so a consumer that
        died and never restarted stays counted forever."""
        client = _client(groups=[_group(consumers=1)], consumers=[_consumer(idle=90_000)])

        health = await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)

        assert health["consumers"] == 1, "the registration is still reported, for ops"
        assert health["live_consumers"] == 0
        assert health["min_idle_ms"] == 90_000

    async def test_a_blocked_consumer_is_live(self):
        """A consumer parked in XREADGROUP(block=N) refreshes idle every N ms."""
        client = _client(groups=[_group()], consumers=[_consumer(idle=4_800)])

        assert (await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS))[
            "live_consumers"
        ] == 1

    async def test_inactive_is_never_read(self):
        """The discriminating case: a healthy consumer on a QUIET stream. `idle` is
        small because it keeps re-blocking; `inactive` — time since the last
        *successful* read — has grown to 10 minutes. Reading `inactive` would report
        this live consumer as dead."""
        client = _client(
            groups=[_group()],
            consumers=[_consumer(idle=200, inactive=600_000)],
        )

        health = await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)

        assert health["live_consumers"] == 1

    async def test_mixed_consumers_count_only_the_live_ones(self):
        client = _client(
            groups=[_group(consumers=3)],
            consumers=[
                _consumer("a", idle=100),
                _consumer("b", idle=200_000),
                _consumer("c", idle=1_000),
            ],
        )

        health = await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)

        assert (health["consumers"], health["live_consumers"]) == (3, 2)
        assert health["min_idle_ms"] == 100


@pytest.mark.asyncio
class TestErrorHandling:
    async def test_group_absent_is_not_an_error(self):
        client = _client(groups=[_group(name="some_other_group")])

        health = await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)

        assert health["exists"] is False
        assert health["error"] is None
        assert health["lag"] is None

    async def test_redis_error_is_reported_not_raised(self):
        client = _client(groups_exc=RedisError("connection lost"))

        health = await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)

        assert health["exists"] is False
        assert "connection lost" in (health["error"] or "")

    async def test_os_error_is_reported_too(self):
        """redis.exceptions.* do NOT descend from OSError; both clauses are needed."""
        client = _client(groups=[_group()], consumers_exc=OSError("socket gone"))

        assert "socket gone" in (
            (await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS))["error"] or ""
        )

    async def test_a_bug_in_our_own_code_is_not_swallowed(self):
        """The blanket `except Exception` is what made the nil-lag TypeError report
        as "the consumer is down". Our bugs must reach the caller as a 500."""
        client = _client(groups_exc=TypeError("int() argument must be..."))

        with pytest.raises(TypeError):
            await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)


@pytest.mark.asyncio
async def test_fields_are_found_on_a_client_without_decode_responses():
    """A bytes key misses every .get("name") lookup, and the helper would then report
    a healthy group as absent."""
    client = _client(
        groups=[{b"name": GROUP.encode(), b"consumers": 1, b"pending": 2, b"lag": 7}],
        consumers=[{b"name": b"worker-1", b"idle": 300, b"pending": 0}],
    )

    health = await consumer_group_health(client, STREAM, GROUP, block_ms=BLOCK_MS)

    assert (health["exists"], health["pending"], health["lag"], health["live_consumers"]) == (
        True,
        2,
        7,
        1,
    )
