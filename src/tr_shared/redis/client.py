"""Shared async Redis client for the process, rebuilt for each event loop."""

import redis.asyncio as aioredis

from tr_shared.redis.pool import LoopBoundRedis

_redis: LoopBoundRedis | None = None


async def get_redis_client(
    url: str,
    max_connections: int = 10,
    decode_responses: bool = True,
    socket_connect_timeout: int = 5,
) -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = LoopBoundRedis(
            url,
            max_connections=max_connections,
            socket_timeout=socket_connect_timeout,
            socket_connect_timeout=socket_connect_timeout,
            decode_responses=decode_responses,
        )
    return _redis.client()


async def close_redis_client() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
