"""The one place a Redis connection pool is configured for the fleet."""

import asyncio
from functools import partial

from redis.asyncio import ConnectionPool, Redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from tr_shared.redis.connection import (
    ProxySafeConnection,
    keepalive_options,
    require_plain_redis_url,
)


def build_connection_pool(
    url: str,
    *,
    max_connections: int,
    socket_timeout: int,
    socket_connect_timeout: int,
    decode_responses: bool,
) -> ConnectionPool:
    require_plain_redis_url(url)
    return ConnectionPool.from_url(
        url,
        connection_class=ProxySafeConnection,
        max_connections=max_connections,
        decode_responses=decode_responses,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
        health_check_interval=10,
        socket_keepalive=True,
        socket_keepalive_options=keepalive_options(),
        retry=Retry(ExponentialBackoff(cap=2, base=0.1), retries=3),
        retry_on_error=[ConnectionError, TimeoutError, OSError],
    )


class LoopBoundRedis:
    def __init__(
        self,
        url: str,
        *,
        max_connections: int,
        socket_timeout: int,
        socket_connect_timeout: int,
        decode_responses: bool,
    ) -> None:
        require_plain_redis_url(url)
        self._build_pool = partial(
            build_connection_pool,
            url,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            decode_responses=decode_responses,
        )
        self._bound: tuple[asyncio.AbstractEventLoop, Redis] | None = None

    def client(self) -> Redis:
        loop = asyncio.get_running_loop()
        if self._bound is None or self._bound[0] is not loop:
            self._bound = (loop, Redis(connection_pool=self._build_pool()))
        return self._bound[1]
