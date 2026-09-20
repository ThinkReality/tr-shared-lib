"""A pooled Redis connection reset by the proxy while idle must heal on the next call.

Reproduces the staging failure: Railway's TCP proxy resets idle client legs,
asyncio surfaces the reset as ``reader.set_exception`` (not EOF), redis-py's
checkout check is blind to it, and the next write hits a closed transport.

The relay below is test-owned scaffolding in front of the lane's real Redis
(``TEST_REDIS_URL``); it forwards bytes both ways and can reset every client
leg with an RST (SO_LINGER 0 + abort), which is what a proxy idle-kill looks
like from the client. Runs under both the default loop and uvloop — the
production error is uvloop's.
"""

import asyncio
import os
import socket
import struct
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

import pytest
import uvloop
from redis.asyncio import ConnectionPool
from redis.exceptions import ConnectionError as RedisConnectionError

import tr_shared.redis.client as redis_module
from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.cache.service import CacheService
from tr_shared.redis.client import close_redis_client, get_redis_client
from tr_shared.redis.connection import ProxySafeConnection

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)

RUNNERS = {"asyncio": asyncio.run, "uvloop": uvloop.run}


class Relay:
    """TCP relay to a real Redis whose client legs can be reset on demand."""

    def __init__(self, target_url: str) -> None:
        parts = urlsplit(target_url)
        self._target = (parts.hostname, parts.port)
        self._parts = parts
        self._client_writers: set[asyncio.StreamWriter] = set()
        self._server: asyncio.AbstractServer | None = None
        self.url = ""

    async def __aenter__(self) -> "Relay":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        userinfo = self._parts.netloc.rsplit("@", 1)[0] + "@" if "@" in self._parts.netloc else ""
        self.url = urlunsplit(self._parts._replace(netloc=f"{userinfo}127.0.0.1:{port}"))
        return self

    async def __aexit__(self, *exc: object) -> None:
        for writer in list(self._client_writers):
            writer.close()
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._client_writers.add(writer)
        up_reader, up_writer = await asyncio.open_connection(*self._target)
        try:
            await asyncio.gather(self._pump(reader, up_writer), self._pump(up_reader, writer))
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            up_writer.close()
            writer.close()
            self._client_writers.discard(writer)

    @staticmethod
    async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()

    def reset_clients(self) -> None:
        for writer in list(self._client_writers):
            if writer.transport.is_closing():
                continue
            sock = writer.get_extra_info("socket")
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            writer.transport.abort()


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


async def _cache_service_read_after_reset():
    async with Relay(TEST_REDIS_URL) as relay:
        adapter = StandardRedisAdapter(url=relay.url)
        assert await adapter.initialize()
        service = CacheService(adapter, key_prefix="itest")
        key = service.build_key(uuid.uuid4().hex)
        try:
            assert await service.set(key, "v", ttl=60)
            await _reset_and_wait_until_client_sees_it(relay, adapter._pool)
            return await service.get_result(key)
        finally:
            await adapter.close()


async def _raw_client_read_after_reset():
    async with Relay(TEST_REDIS_URL) as relay:
        redis_module._client = None
        client = await get_redis_client(relay.url, max_connections=2)
        key = f"itest:{uuid.uuid4().hex}"
        try:
            await client.set(key, "v", ex=60)
            await _reset_and_wait_until_client_sees_it(relay, client.connection_pool)
            return await client.get(key)
        finally:
            await close_redis_client()


@pytest.mark.parametrize("runner", RUNNERS.values(), ids=RUNNERS.keys())
def test_cache_service_hit_survives_proxy_reset(runner):
    with write_guard_hits() as hits:
        result = runner(_cache_service_read_after_reset())
    assert result.error is None, f"cache read failed after reset: {result.error!r}"
    assert result.hit and result.value == "v"
    assert not hits, f"healed by the write guard (retry + backoff), not at checkout: {hits!r}"


@pytest.mark.parametrize("runner", RUNNERS.values(), ids=RUNNERS.keys())
def test_get_redis_client_get_survives_proxy_reset(runner):
    with write_guard_hits() as hits:
        value = runner(_raw_client_read_after_reset())
    assert value == "v"
    assert not hits, f"healed by the write guard (retry + backoff), not at checkout: {hits!r}"
