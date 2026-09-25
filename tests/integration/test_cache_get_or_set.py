import os
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from redis.asyncio import Redis

from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.cache.service import CacheService

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)


class Fetch:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.calls = 0
        self._result = result
        self._error = error

    async def __call__(self) -> Any:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


async def _service(url: str, *, reachable: bool = True) -> AsyncIterator[CacheService]:
    adapter = StandardRedisAdapter(url=url)
    assert await adapter.initialize() is reachable
    try:
        yield CacheService(adapter, key_prefix="itest")
    finally:
        await adapter.close()


@pytest.fixture
async def service() -> AsyncIterator[CacheService]:
    async for svc in _service(TEST_REDIS_URL):
        yield svc


@pytest.fixture
async def read_only_service() -> AsyncIterator[CacheService]:
    admin = Redis.from_url(TEST_REDIS_URL)
    user, password = f"itest-ro-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    await admin.acl_setuser(
        user,
        enabled=True,
        passwords=[f"+{password}"],
        keys=["*"],
        commands=["+@read", "+ping", "+select"],
    )
    parts = urlsplit(TEST_REDIS_URL)
    host = parts.netloc.rsplit("@", 1)[-1]
    url = urlunsplit(parts._replace(netloc=f"{user}:{password}@{host}"))
    try:
        async for svc in _service(url):
            yield svc
    finally:
        await admin.acl_deluser(user)
        await admin.aclose()


@pytest.fixture
async def unreachable_service() -> AsyncIterator[CacheService]:
    async for svc in _service("redis://127.0.0.1:1/0", reachable=False):
        yield svc


def _key(svc: CacheService) -> str:
    return svc.build_key(uuid.uuid4().hex)


async def test_hit_does_not_fetch(service: CacheService) -> None:
    key = _key(service)
    await service.set(key, {"id": 1}, ttl=60)
    fetch = Fetch({"id": 2})

    assert await service.get_or_set(key, fetch, ttl=60) == {"id": 1}
    assert fetch.calls == 0


async def test_miss_fetches_once_and_caches(service: CacheService) -> None:
    key = _key(service)
    fetch = Fetch({"id": 42})

    assert await service.get_or_set(key, fetch, ttl=60) == {"id": 42}
    assert fetch.calls == 1
    assert await service.get(key) == {"id": 42}


async def test_none_is_not_cached(service: CacheService) -> None:
    key = _key(service)

    assert await service.get_or_set(key, Fetch(None), ttl=60) is None
    assert await service.exists(key) is False


async def test_fetch_error_propagates_after_one_call(service: CacheService) -> None:
    fetch = Fetch(error=RuntimeError("upstream down"))

    with pytest.raises(RuntimeError, match="upstream down"):
        await service.get_or_set(_key(service), fetch, ttl=60)
    assert fetch.calls == 1


async def test_read_failure_is_a_miss(unreachable_service: CacheService) -> None:
    fetch = Fetch({"id": 7})

    assert await unreachable_service.get_or_set("itest:any", fetch, ttl=60) == {"id": 7}
    assert fetch.calls == 1


async def test_write_failure_still_returns_fetched_data(
    read_only_service: CacheService,
) -> None:
    fetch = Fetch({"id": 9})

    assert await read_only_service.get_or_set(_key(read_only_service), fetch, ttl=60) == {"id": 9}
    assert fetch.calls == 1


async def test_encode_failure_still_returns_fetched_data(service: CacheService) -> None:
    circular: dict[str, Any] = {}
    circular["self"] = circular
    key = _key(service)
    fetch = Fetch(circular)

    assert await service.get_or_set(key, fetch, ttl=60) is circular
    assert fetch.calls == 1
    assert await service.exists(key) is False
