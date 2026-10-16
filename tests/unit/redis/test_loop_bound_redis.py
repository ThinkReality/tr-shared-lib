import asyncio

import pytest

from tr_shared.redis import LoopBoundRedis


def _store() -> LoopBoundRedis:
    return LoopBoundRedis(
        "redis://localhost:6379/0",
        max_connections=1,
        socket_timeout=1,
        socket_connect_timeout=1,
        decode_responses=True,
    )


def test_one_event_loop_reuses_one_client():
    store = _store()

    async def twice():
        return store.client(), store.client()

    first, second = asyncio.run(twice())

    assert first is second


def test_each_event_loop_gets_its_own_client():
    store = _store()

    async def once():
        return store.client()

    assert asyncio.run(once()) is not asyncio.run(once())


def test_closing_drops_the_bound_client():
    store = _store()

    async def close_between():
        first = store.client()
        await store.aclose()
        return first, store.client()

    first, second = asyncio.run(close_between())

    assert first is not second


def test_a_url_the_pool_cannot_serve_is_refused_at_construction():
    with pytest.raises(ValueError, match="only supports redis://"):
        LoopBoundRedis(
            "rediss://localhost:6379/0",
            max_connections=1,
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=True,
        )
