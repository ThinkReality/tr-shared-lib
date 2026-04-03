"""
Shared async Redis client singleton with connection pooling.

Extracted from tr-lead-management's singleton pattern — the best balance
of thread-safety, connection pooling, and graceful error handling across
all 10 service implementations.
"""

import redis.asyncio as aioredis

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

    Args:
        url: Redis connection URL (e.g., ``redis://host:6379/0``).
        max_connections: Max pool size. 10 is plenty for most services.
        decode_responses: Decode bytes to str automatically.
        socket_connect_timeout: Seconds before connection attempt times out.
    """
    global _client
    if _client is None:
        pool = aioredis.ConnectionPool.from_url(
            url,
            max_connections=max_connections,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
        )
        _client = aioredis.Redis(connection_pool=pool)
    return _client


async def close_redis_client() -> None:
    """Close the shared Redis client and release all connections."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
