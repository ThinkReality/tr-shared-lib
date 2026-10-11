"""A connection the proxy resets while a command is in flight must heal on the same call.

The relay forwards to the lane's real Redis (``TEST_REDIS_URL``). Once armed, it resets the
client leg that sends the next command, before that command reaches Redis, which is what a
proxy killing an in-use connection looks like from the client.
"""

import asyncio
import os
import socket
import struct
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
import uvloop
from redis.asyncio import Redis

from tr_shared.redis.pool import build_connection_pool

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)

RUNNERS = {"asyncio": asyncio.run, "uvloop": uvloop.run}


class ResetNextCommandRelay:
    def __init__(self, target_url: str) -> None:
        self._parts = urlsplit(target_url)
        self._armed = False
        self.resets = 0
        self.url = ""

    async def __aenter__(self) -> "ResetNextCommandRelay":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        netloc = self._parts.netloc
        userinfo = netloc.rsplit("@", 1)[0] + "@" if "@" in netloc else ""
        self.url = urlunsplit(self._parts._replace(netloc=f"{userinfo}127.0.0.1:{port}"))
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._server.close()
        await self._server.wait_closed()

    def arm(self) -> None:
        self._armed = True

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        up_reader, up_writer = await asyncio.open_connection(self._parts.hostname, self._parts.port)
        try:
            await asyncio.gather(
                self._client_to_redis(reader, writer, up_writer),
                self._pump(up_reader, writer),
            )
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            up_writer.close()
            writer.close()

    async def _client_to_redis(
        self,
        reader: asyncio.StreamReader,
        client: asyncio.StreamWriter,
        upstream: asyncio.StreamWriter,
    ) -> None:
        try:
            while data := await reader.read(65536):
                if self._armed:
                    self._armed = False
                    self.resets += 1
                    sock = client.get_extra_info("socket")
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    client.transport.abort()
                    return
                upstream.write(data)
                await upstream.drain()
        finally:
            upstream.close()

    @staticmethod
    async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()


async def _get_across_an_in_flight_reset() -> tuple[str | None, int]:
    assert TEST_REDIS_URL is not None
    async with ResetNextCommandRelay(TEST_REDIS_URL) as relay:
        pool = build_connection_pool(
            relay.url,
            max_connections=2,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
        client = Redis(connection_pool=pool)
        key = f"itest:{uuid.uuid4().hex}"
        try:
            await client.set(key, "v", ex=60)
            relay.arm()
            value = await client.get(key)
            return value, relay.resets
        finally:
            await client.aclose()
            await pool.aclose()


@pytest.mark.parametrize("runner", RUNNERS.values(), ids=RUNNERS.keys())
def test_a_command_reset_in_flight_succeeds_on_the_same_call(runner):
    value, resets = runner(_get_across_an_in_flight_reset())

    assert resets == 1
    assert value == "v"
