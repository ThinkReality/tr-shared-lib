"""Shared pytest fixtures for tr-shared-lib tests."""

import pytest
import fakeredis
import fakeredis.aioredis as fakeredis_aioredis


@pytest.fixture
def fake_redis_server():
    """Shared FakeServer instance (enables Lua scripting via lupa)."""
    return fakeredis.FakeServer()


@pytest.fixture
def fake_redis(fake_redis_server):
    """Synchronous fakeredis client."""
    return fakeredis.FakeRedis(server=fake_redis_server, decode_responses=True)


@pytest.fixture
async def async_fake_redis(fake_redis_server):
    """Async fakeredis client with Lua scripting support (requires lupa)."""
    client = fakeredis_aioredis.FakeRedis(server=fake_redis_server, decode_responses=True)
    yield client
    await client.aclose()
