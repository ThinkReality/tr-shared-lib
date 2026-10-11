"""Retrying must heal a reset without multiplying the cost of a dead or silent server."""

import asyncio
import socket
import time

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError, TimeoutError

from tr_shared.redis.pool import build_connection_pool


def _client(url: str, timeout: int) -> Redis:
    pool = build_connection_pool(
        url,
        max_connections=1,
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        decode_responses=True,
    )
    return Redis(connection_pool=pool)


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_a_silent_server_costs_one_timeout_not_one_per_retry():
    connections = 0

    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connections
        connections += 1
        await reader.read()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = _client(f"redis://127.0.0.1:{port}/0", timeout=1)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            await client.get("k")
    finally:
        await client.aclose()
        server.close()

    assert time.monotonic() - started < 1.5
    assert connections == 1


async def test_a_refused_server_fails_at_once():
    client = _client(f"redis://127.0.0.1:{_closed_port()}/0", timeout=1)
    started = time.monotonic()
    try:
        with pytest.raises(ConnectionError):
            await client.get("k")
    finally:
        await client.aclose()

    assert time.monotonic() - started < 0.2
