"""One pool builder: the guards, keepalive and retry policy are configured once, and
each call site's kwargs are pinned so the two paths cannot drift apart again."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.backoff import ExponentialBackoff

import tr_shared.redis.client as redis_module
from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.redis.client import get_redis_client
from tr_shared.redis.connection import ProxySafeConnection, keepalive_options
from tr_shared.redis.pool import build_connection_pool

URL = "redis://:pw@redis.example:6379/3"


@pytest.fixture(autouse=True)
def reset_redis_client():
    redis_module._client = None
    yield
    redis_module._client = None


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
        with (
            patch("tr_shared.redis.client.build_connection_pool") as build,
            patch("tr_shared.redis.client.aioredis.Redis"),
        ):
            await get_redis_client(
                URL, max_connections=7, decode_responses=False, socket_connect_timeout=3
            )
        build.assert_called_once_with(
            URL,
            max_connections=7,
            socket_timeout=3,
            socket_connect_timeout=3,
            decode_responses=False,
        )

    async def test_standard_redis_adapter_keeps_separate_timeouts_and_decodes(self):
        with (
            patch("tr_shared.cache.adapters.standard_redis.build_connection_pool") as build,
            patch("tr_shared.cache.adapters.standard_redis.Redis") as redis_cls,
        ):
            redis_cls.return_value = MagicMock(ping=AsyncMock(return_value=True))
            adapter = StandardRedisAdapter(
                URL, max_connections=9, socket_timeout=4, socket_connect_timeout=2
            )
            assert await adapter.initialize()
        build.assert_called_once_with(
            URL,
            max_connections=9,
            socket_timeout=4,
            socket_connect_timeout=2,
            decode_responses=True,
        )
