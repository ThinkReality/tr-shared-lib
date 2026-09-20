"""A live pooled connection carries SO_KEEPALIVE and the TCP probe options the
platform supports (idle 60 s / interval 10 s / count 3)."""

import os
import socket

import pytest

import tr_shared.redis.client as redis_module
from tr_shared.redis.client import close_redis_client, get_redis_client
from tr_shared.redis.connection import KEEPALIVE_COUNT, KEEPALIVE_IDLE_S, KEEPALIVE_INTERVAL_S

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)


@pytest.fixture
async def live_socket():
    redis_module._client = None
    client = await get_redis_client(TEST_REDIS_URL)
    conn = await client.connection_pool.get_connection()
    try:
        yield conn._writer.transport.get_extra_info("socket")
    finally:
        await client.connection_pool.release(conn)
        await close_redis_client()


async def test_so_keepalive_enabled(live_socket):
    assert live_socket.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0


@pytest.mark.parametrize(
    ("constant", "expected"),
    [
        ("TCP_KEEPIDLE", KEEPALIVE_IDLE_S),
        ("TCP_KEEPINTVL", KEEPALIVE_INTERVAL_S),
        ("TCP_KEEPCNT", KEEPALIVE_COUNT),
    ],
)
async def test_tcp_probe_options_read_back(live_socket, constant, expected):
    option = getattr(socket, constant, None)
    if option is None:
        pytest.skip(f"{constant} not defined on this platform")
    assert live_socket.getsockopt(socket.SOL_TCP, option) == expected
