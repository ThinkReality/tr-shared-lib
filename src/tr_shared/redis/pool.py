"""The one place a Redis connection pool is configured for the fleet."""

from redis.asyncio import ConnectionPool
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
