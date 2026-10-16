"""One pool builder: the guards, keepalive and retry policy are configured once, and
each call site's kwargs are pinned so the two paths cannot drift apart again."""

from unittest.mock import AsyncMock, patch

import pytest
from redis.asyncio import Redis
from redis.backoff import ExponentialBackoff

from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.redis.client import close_redis_client, get_redis_client
from tr_shared.redis.connection import ProxySafeConnection, keepalive_options
from tr_shared.redis.pool import build_connection_pool

URL = "redis://:pw@redis.example:6379/3"


@pytest.fixture(autouse=True)
async def no_shared_client():
    await close_redis_client()
    yield
    await close_redis_client()


class TestBuildConnectionPool:
    def test_pool_is_configured_once(self):
        pool = build_connection_pool(
            URL,
            max_connections=7,
            socket_timeout=4,
            socket_connect_timeout=2,
            decode_responses=False,
        )
        kwargs = pool.connection_kwargs
        assert pool.connection_class is ProxySafeConnection
        assert pool.max_connections == 7
        assert kwargs["host"] == "redis.example"
        assert kwargs["port"] == 6379
        assert kwargs["db"] == 3
        assert kwargs["password"] == "pw"
        assert kwargs["decode_responses"] is False
        assert kwargs["socket_timeout"] == 4
        assert kwargs["socket_connect_timeout"] == 2
        assert kwargs["health_check_interval"] == 10
        assert kwargs["socket_keepalive"] is True
        assert kwargs["socket_keepalive_options"] == keepalive_options()
        assert kwargs["retry_on_error"] == [ConnectionError, TimeoutError, OSError]
        retry = kwargs["retry"]
        assert retry._retries == 3
        assert isinstance(retry._backoff, ExponentialBackoff)
        assert (retry._backoff._cap, retry._backoff._base) == (2, 0.1)

    @pytest.mark.parametrize("url", ["rediss://host:6379/0", "unix:///tmp/redis.sock"])
    def test_url_that_would_swap_connection_class_is_rejected(self, url):
        with pytest.raises(ValueError, match="only supports redis://"):
            build_connection_pool(
                url,
                max_connections=1,
                socket_timeout=1,
                socket_connect_timeout=1,
                decode_responses=True,
            )


class TestCallSitesPinTheirKwargs:
    async def test_get_redis_client_uses_connect_timeout_for_both_timeouts(self):
        client = await get_redis_client(
            URL, max_connections=7, decode_responses=False, socket_connect_timeout=3
        )

        pool = client.connection_pool
        assert pool.max_connections == 7
        assert pool.connection_kwargs["socket_timeout"] == 3
        assert pool.connection_kwargs["socket_connect_timeout"] == 3
        assert pool.connection_kwargs["decode_responses"] is False

    async def test_standard_redis_adapter_keeps_separate_timeouts_and_decodes(self):
        adapter = StandardRedisAdapter(
            URL, max_connections=9, socket_timeout=4, socket_connect_timeout=2
        )
        with patch.object(Redis, "ping", AsyncMock(return_value=True)):
            assert await adapter.initialize()

        pool = adapter.client.connection_pool
        assert pool.max_connections == 9
        assert pool.connection_kwargs["socket_timeout"] == 4
        assert pool.connection_kwargs["socket_connect_timeout"] == 2
        assert pool.connection_kwargs["decode_responses"] is True
