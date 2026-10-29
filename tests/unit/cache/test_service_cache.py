from tr_shared.cache import ServiceCache

UNREACHABLE = "redis://127.0.0.1:1/0"


async def test_an_unreachable_redis_answers_no_cache_and_no_client() -> None:
    cache = ServiceCache(UNREACHABLE, key_prefix="test:svc", max_connections=2)

    assert await cache.service() is None
    assert await cache.client() is None


async def test_closing_a_cache_that_never_connected_is_a_no_op() -> None:
    await ServiceCache(UNREACHABLE, key_prefix="test:svc", max_connections=2).close()
