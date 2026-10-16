import asyncio
import os
import uuid

import pytest

from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.redis import close_redis_client, get_redis_client

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)


def test_a_cache_adapter_serves_every_event_loop():
    assert TEST_REDIS_URL is not None
    adapter = StandardRedisAdapter(url=TEST_REDIS_URL)
    key = f"itest:{uuid.uuid4().hex}"
    assert asyncio.run(adapter.initialize())

    try:
        asyncio.run(adapter.set(key, "v", ttl=60))
        assert asyncio.run(adapter.get(key)) == "v"
    finally:
        asyncio.run(adapter.close())


def test_the_shared_client_serves_every_event_loop():
    assert TEST_REDIS_URL is not None
    key = f"itest:{uuid.uuid4().hex}"

    async def write() -> None:
        await (await get_redis_client(TEST_REDIS_URL)).set(key, "v", ex=60)

    async def read() -> str | None:
        return await (await get_redis_client(TEST_REDIS_URL)).get(key)

    try:
        asyncio.run(write())
        assert asyncio.run(read()) == "v"
    finally:
        asyncio.run(close_redis_client())
