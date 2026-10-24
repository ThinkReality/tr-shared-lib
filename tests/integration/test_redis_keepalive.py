"""A live pooled connection carries SO_KEEPALIVE and the TCP probe options the
platform supports (idle 60 s / interval 10 s / count 3)."""

import socket

import pytest

from tr_shared.redis.client import close_redis_client, get_redis_client
from tr_shared.redis.connection import KEEPALIVE_COUNT, KEEPALIVE_IDLE_S, KEEPALIVE_INTERVAL_S

pytestmark = pytest.mark.integration


@pytest.fixture
async def live_socket(redis_url):
    await close_redis_client()
    client = await get_redis_client(redis_url)
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
