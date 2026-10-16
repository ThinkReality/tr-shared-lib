import asyncio

import pytest

from tr_shared.redis import close_redis_client, get_redis_client

URL = "redis://localhost:6379/0"


@pytest.fixture(autouse=True)
def no_shared_client():
    asyncio.run(close_redis_client())
    yield
    asyncio.run(close_redis_client())


def test_one_event_loop_reuses_one_client():
    async def twice():
        return await get_redis_client(URL), await get_redis_client(URL)

    first, second = asyncio.run(twice())

    assert first is second


def test_each_event_loop_gets_its_own_client():
    assert asyncio.run(get_redis_client(URL)) is not asyncio.run(get_redis_client(URL))


def test_the_pool_takes_the_requested_settings():
    async def pool():
        client = await get_redis_client(URL, max_connections=3, decode_responses=False)
        return client.connection_pool

    built = asyncio.run(pool())

    assert built.max_connections == 3
    assert built.connection_kwargs["decode_responses"] is False


def test_closing_forgets_the_client():
    async def close_between():
        first = await get_redis_client(URL)
        await close_redis_client()
        return first, await get_redis_client(URL)

    first, second = asyncio.run(close_between())

    assert first is not second
