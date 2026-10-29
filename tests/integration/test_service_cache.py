import asyncio

import pytest

from tr_shared.cache import ServiceCache

pytestmark = pytest.mark.integration


async def test_the_cache_is_built_once_and_hands_out_its_own_client(redis_url: str) -> None:
    cache = ServiceCache(redis_url, key_prefix="itest:svc", max_connections=2)
    try:
        first = await cache.service()

        assert first is not None
        assert await cache.service() is first
        assert await cache.client() is first.cache.client
        assert first.key_prefix == cache.key_prefix == "itest:svc"
    finally:
        await cache.close()


async def test_close_releases_the_cache_and_the_next_call_builds_a_fresh_one(
    redis_url: str,
) -> None:
    cache = ServiceCache(redis_url, key_prefix="itest:svc", max_connections=2)
    first = await cache.service()
    await cache.close()
    try:
        second = await cache.service()
        client = await cache.client()

        assert second is not None and second is not first
        assert client is not None and await client.ping()
    finally:
        await cache.close()


async def test_concurrent_first_callers_share_one_cache(redis_url: str) -> None:
    cache = ServiceCache(redis_url, key_prefix="itest:svc", max_connections=2)
    try:
        first, second = await asyncio.gather(cache.service(), cache.service())

        assert first is not None
        assert first is second is await cache.service()
    finally:
        await cache.close()
