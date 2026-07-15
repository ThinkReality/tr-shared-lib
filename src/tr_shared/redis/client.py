"""
Shared async Redis client singleton with connection pooling.

Balances thread-safety, connection pooling, and graceful error handling.
"""

import redis.asyncio as aioredis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

_client: aioredis.Redis | None = None


async def get_redis_client(
    url: str,
    max_connections: int = 10,
    decode_responses: bool = True,
    socket_connect_timeout: int = 5,
) -> aioredis.Redis:
    """
    Get or create a shared async Redis client singleton.

    Uses ConnectionPool for efficient connection reuse across the service.
    Thread-safe via redis-py's internal locking on the pool.
    """
    global _client
    if _client is None:
        retry = Retry(ExponentialBackoff(cap=2, base=0.1), retries=3)
        pool = aioredis.ConnectionPool.from_url(
            url,
            max_connections=max_connections,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_connect_timeout,
            health_check_interval=10,
            socket_keepalive=True,
            retry=retry,
            retry_on_error=[ConnectionError, TimeoutError, OSError],
        )
        _client = aioredis.Redis(connection_pool=pool)
    return _client


async def close_redis_client() -> None:
    """Close the shared Redis client and release all connections."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
