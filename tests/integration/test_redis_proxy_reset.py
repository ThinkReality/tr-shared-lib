"""A pooled Redis connection reset by the proxy while idle must heal on the next call.

Reproduces the staging failure: Railway's TCP proxy resets idle client legs,
asyncio surfaces the reset as ``reader.set_exception`` (not EOF), redis-py's
checkout check is blind to it, and the next write hits a closed transport.

The relay (``network_faults.Relay``) is test-owned scaffolding in front of the lane's real Redis
(the ``redis_url`` fixture); it forwards bytes both ways and can reset every client
leg with an RST (SO_LINGER 0 + abort), which is what a proxy idle-kill looks
like from the client. Runs under both the default loop and uvloop — the
production error is uvloop's.
"""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import uvloop
from redis.asyncio import ConnectionPool
from redis.exceptions import ConnectionError as RedisConnectionError

from tests.integration.network_faults import Relay
from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.cache.service import CacheService
from tr_shared.redis.client import close_redis_client, get_redis_client
from tr_shared.redis.connection import ProxySafeConnection

pytestmark = pytest.mark.integration

RUNNERS = {"asyncio": asyncio.run, "uvloop": uvloop.run}


async def _reset_and_wait_until_client_sees_it(relay: Relay, pool: ConnectionPool) -> None:
    """The client observes the RST one loop iteration after the relay closes; poll
    redis-py's idle list so the next command is issued only once every pooled
    transport is closing — otherwise the read, not the checkout, would fail."""
    relay.reset_clients()
    async with asyncio.timeout(2):
        while not all(c._writer.transport.is_closing() for c in pool._available_connections):
            await asyncio.sleep(0.005)


@contextmanager
def write_guard_hits() -> Iterator[list[RedisConnectionError]]:
    """Records every ConnectionError the write-time guard raises; the checkout guard
    is expected to catch a reset first, so a healthy run records none."""
    original = ProxySafeConnection._send_packed_command
    hits: list[RedisConnectionError] = []

    async def counting(self: ProxySafeConnection, command) -> None:
        try:
            await original(self, command)
        except RedisConnectionError as exc:
            hits.append(exc)
            raise

    ProxySafeConnection._send_packed_command = counting  # type: ignore[method-assign]
    try:
        yield hits
    finally:
        ProxySafeConnection._send_packed_command = original  # type: ignore[method-assign]


async def _cache_service_read_after_reset(redis_url: str):
    async with Relay(redis_url) as relay:
        adapter = StandardRedisAdapter(url=relay.url)
        assert await adapter.initialize()
        service = CacheService(adapter, key_prefix="itest")
        key = service.build_key(uuid.uuid4().hex)
        try:
            assert await service.set(key, "v", ttl=60)
            await _reset_and_wait_until_client_sees_it(relay, adapter.client.connection_pool)
            return await service.get_result(key)
        finally:
            await adapter.close()


async def _raw_client_read_after_reset(redis_url: str):
    async with Relay(redis_url) as relay:
        await close_redis_client()
        client = await get_redis_client(relay.url, max_connections=2)
        key = f"itest:{uuid.uuid4().hex}"
        try:
            await client.set(key, "v", ex=60)
            await _reset_and_wait_until_client_sees_it(relay, client.connection_pool)
            return await client.get(key)
        finally:
            await close_redis_client()


@pytest.mark.parametrize("runner", RUNNERS.values(), ids=RUNNERS.keys())
def test_cache_service_hit_survives_proxy_reset(runner, redis_url):
    with write_guard_hits() as hits:
        result = runner(_cache_service_read_after_reset(redis_url))
    assert result.error is None, f"cache read failed after reset: {result.error!r}"
    assert result.hit and result.value == "v"
    assert not hits, f"healed by the write guard (retry + backoff), not at checkout: {hits!r}"


@pytest.mark.parametrize("runner", RUNNERS.values(), ids=RUNNERS.keys())
def test_get_redis_client_get_survives_proxy_reset(runner, redis_url):
    with write_guard_hits() as hits:
        value = runner(_raw_client_read_after_reset(redis_url))
    assert value == "v"
    assert not hits, f"healed by the write guard (retry + backoff), not at checkout: {hits!r}"
