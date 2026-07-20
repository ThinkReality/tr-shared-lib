"""One-time maintenance: drain the pre-0.35.0 stuck Pending-Entry-List backlog.

Before the PEL/XAUTOCLAIM fix, any consumer crash between XREADGROUP and XACK
orphaned the in-flight entry forever, and consumer-name churn (hostname-pid) left
empty zombie consumers behind. This script clears that historical backlog so the
new claimer starts from a clean slate:

  - XACK every pending entry in each target group (accept the historical
    audit-trail gap — dev-phase, no real users/data), then
  - XGROUP DELCONSUMER every now-empty consumer.

Idempotent: a second run finds nothing pending and is a no-op. NOT a recurring
job — from 0.35.0 on, new orphans are auto-recovered by the claimer.

Usage:
    REDIS_URL='redis://:devpassword@localhost:6382/0' \
        python scripts/purge_stuck_pel.py

Optionally pass a stream name (default tr_event_bus) and space-separated groups;
with no groups it discovers every group on the stream.
"""

from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as redis


async def _purge_group(client: redis.Redis, stream: str, group: str) -> tuple[int, int]:
    acked = 0
    while True:
        pending = await client.xpending_range(stream, group, min="-", max="+", count=500)
        if not pending:
            break
        ids = [entry["message_id"] for entry in pending]
        acked += await client.xack(stream, group, *ids)
        if len(pending) < 500:
            break

    # Delete now-empty consumers. XGROUP DELCONSUMER returns the pending count the
    # consumer had (0 here), not a deletion flag — so count deletions ourselves.
    deleted = 0
    for consumer in await client.xinfo_consumers(stream, group):
        if int(consumer.get("pending", 0)) == 0:
            await client.xgroup_delconsumer(stream, group, consumer["name"])
            deleted += 1
    return acked, deleted


async def main() -> None:
    url = os.getenv("REDIS_URL")
    if not url:
        sys.exit("REDIS_URL not set")
    stream = sys.argv[1] if len(sys.argv) > 1 else "tr_event_bus"
    groups = sys.argv[2:]

    client = redis.from_url(url, decode_responses=True)
    try:
        if not groups:
            groups = [g["name"] for g in await client.xinfo_groups(stream)]
        total_acked = total_deleted = 0
        for group in groups:
            acked, deleted = await _purge_group(client, stream, group)
            total_acked += acked
            total_deleted += deleted
            print(f"{group:32} acked={acked:>5}  zombies_deleted={deleted}")
        print(f"{'TOTAL':32} acked={total_acked:>5}  zombies_deleted={total_deleted}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
