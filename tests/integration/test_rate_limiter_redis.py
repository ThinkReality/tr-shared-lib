import asyncio
import os
import time
import uuid

import pytest
from redis.asyncio import Redis

from tr_shared.rate_limiter import RateLimitConfig, RateLimiter, WindowConfig

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)

TWO_PER_MINUTE = RateLimitConfig(windows=[WindowConfig(limit=2, window_seconds=60)])


async def test_a_url_limiter_counts_in_redis():
    assert TEST_REDIS_URL is not None
    limiter = RateLimiter(redis_url=TEST_REDIS_URL, enable_memory_fallback=False)
    key = f"itest:{uuid.uuid4().hex}"

    verdicts = [(await limiter.check(key, TWO_PER_MINUTE)).is_blocked for _ in range(3)]

    inspector = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        assert await inspector.get(f"{key}:60s") == "3"
    finally:
        await inspector.aclose()
    assert verdicts == [False, False, True]


async def test_a_silent_redis_falls_back_within_the_client_timeout():
    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    limiter = RateLimiter(redis_url=f"redis://127.0.0.1:{port}/0")
    started = time.monotonic()
    try:
        info = await asyncio.wait_for(limiter.check("k", TWO_PER_MINUTE), timeout=5)
    finally:
        server.close()

    assert time.monotonic() - started < 2
    assert info.is_blocked is False


async def test_a_provider_supplies_the_client_on_every_check():
    assert TEST_REDIS_URL is not None
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    calls = 0

    async def provider() -> Redis:
        nonlocal calls
        calls += 1
        return client

    limiter = RateLimiter(redis_provider=provider, enable_memory_fallback=False)
    key = f"itest:{uuid.uuid4().hex}"
    try:
        await limiter.check(key, TWO_PER_MINUTE)
        await limiter.check(key, TWO_PER_MINUTE)
        assert await client.get(f"{key}:60s") == "2"
    finally:
        await client.aclose()
    assert calls == 2


async def test_a_provider_with_no_client_uses_the_memory_fallback():
    async def provider() -> None:
        return None

    limiter = RateLimiter(redis_provider=provider)

    verdicts = [(await limiter.check("k", TWO_PER_MINUTE)).is_blocked for _ in range(3)]

    assert verdicts == [False, False, True]


@pytest.mark.parametrize(
    "sources",
    [
        {"redis_url": "redis://localhost:6379/0", "redis_client": object()},
        {"redis_url": "redis://localhost:6379/0", "redis_provider": object()},
        {"redis_client": object(), "redis_provider": object()},
    ],
)
def test_two_redis_sources_are_refused(sources):
    with pytest.raises(ValueError, match="at most one"):
        RateLimiter(**sources)


def test_a_url_the_pool_cannot_serve_is_refused_at_construction():
    with pytest.raises(ValueError, match="only supports redis://"):
        RateLimiter(redis_url="rediss://localhost:6379/0")
