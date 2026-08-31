"""Liveness and backlog for one Redis Streams consumer group.

Written once here because it was written twice in tr-crm-core and read wrong three
ways. Each of those three is pinned by a test in ``tests/unit/events/test_group_health.py``:

* **``lag`` can be nil.** Redis reports it as *present and nil* whenever it cannot
  reconcile ``entries-read`` with the stream — after any ``XDEL`` past the group's
  read position, or for a group created at an arbitrary mid-stream id. redis-py
  surfaces that as ``None``, so ``int(group.get("lag", 0))`` raises ``TypeError``:
  the ``.get`` default never fires, because the key *is* there. Unknown and zero are
  different answers, so ``lag`` stays ``int | None`` and is never coerced.

* **``consumers`` counts registrations, not processes.** ``EventConsumer.stop()``
  issues no ``XGROUP DELCONSUMER``, and the startup sweep only removes consumers
  idle past 24h — so a consumer that dies and never restarts stays counted forever.
  Liveness comes from per-consumer ``idle`` instead.

* **``inactive`` is the obvious-looking wrong field.** Redis >= 7.2 defines it as time
  since the last *successful* read, so it is ``-1`` before a consumer's first read and
  grows without bound for a perfectly healthy consumer on a quiet stream. ``idle`` is
  time since the last *attempted* interaction, which is what a consumer blocked in
  ``XREADGROUP(block=N)`` refreshes every N ms. Only ``idle`` is read here.
"""

from __future__ import annotations

from typing import Any, TypedDict

import redis.asyncio as redis
from redis.exceptions import RedisError

from tr_shared.logging import get_logger

logger = get_logger(__name__)

# A consumer blocked in XREADGROUP(block=block_ms) refreshes `idle` every block_ms.
# Three windows tolerates one missed cycle plus scheduling jitter without flapping.
DEFAULT_LIVENESS_MULTIPLIER = 3


class GroupHealth(TypedDict):
    group: str
    exists: bool
    consumers: int
    live_consumers: int
    pending: int
    lag: int | None
    min_idle_ms: int | None
    error: str | None


def _text(value: Any) -> str:
    """Field names survive a client built without ``decode_responses``.

    A bytes key silently misses every ``.get("name")`` lookup and the helper would
    then report a healthy group as absent — the same shape of bug this module exists
    to remove.
    """
    return value.decode() if isinstance(value, bytes | bytearray) else str(value)


def _field(record: dict[Any, Any], name: str) -> Any:
    for key, value in record.items():
        if _text(key) == name:
            return value
    return None


def _unhealthy(group: str, error: str | None) -> GroupHealth:
    return GroupHealth(
        group=group,
        exists=False,
        consumers=0,
        live_consumers=0,
        pending=0,
        lag=None,
        min_idle_ms=None,
        error=error,
    )


async def consumer_group_health(
    client: redis.Redis,
    stream: str,
    group: str,
    *,
    block_ms: int,
    liveness_multiplier: int = DEFAULT_LIVENESS_MULTIPLIER,
) -> GroupHealth:
    """Report one consumer group's liveness and backlog.

    Takes an already-built client rather than a URL so callers pass their existing
    pool instead of opening a second one for a health probe.

    Only ``RedisError`` and ``OSError`` are caught, and they are reported in
    ``error``. A ``TypeError`` raised by this module's own arithmetic must reach the
    caller as a 500 — reporting our bug to ops as "the consumer is down" is what sent
    the last investigation in the wrong direction. Note that ``redis.exceptions.*``
    do not descend from ``OSError``; both clauses are load-bearing.
    """
    idle_threshold = block_ms * liveness_multiplier

    try:
        groups = await client.xinfo_groups(stream)
    except (RedisError, OSError) as exc:
        logger.warning("Could not read consumer groups on '%s': %s", stream, exc)
        return _unhealthy(group, str(exc))

    record = next((g for g in groups if _text(_field(g, "name")) == group), None)
    if record is None:
        return _unhealthy(group, None)

    try:
        consumers = await client.xinfo_consumers(stream, group)
    except (RedisError, OSError) as exc:
        logger.warning("Could not read consumers of group '%s': %s", group, exc)
        return _unhealthy(group, str(exc))

    idles = [int(_field(c, "idle") or 0) for c in consumers]
    lag = _field(record, "lag")

    return GroupHealth(
        group=group,
        exists=True,
        consumers=int(_field(record, "consumers") or 0),
        live_consumers=sum(1 for idle in idles if idle < idle_threshold),
        pending=int(_field(record, "pending") or 0),
        # Passed through exactly as Redis answered. `or 0` here would re-hide the
        # nil case this module was written to expose.
        lag=None if lag is None else int(lag),
        min_idle_ms=min(idles) if idles else None,
        error=None,
    )
