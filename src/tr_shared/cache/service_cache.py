"""A service's one cache per process: the CacheService and the pooled Redis client behind it."""

import logging
from typing import TYPE_CHECKING, cast

from tr_shared.cache.factory import CacheProviderFactory
from tr_shared.cache.service import CacheService

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ServiceCache:
    def __init__(
        self,
        redis_url: str,
        key_prefix: str,
        *,
        max_connections: int,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
    ) -> None:
        self._redis_url = redis_url
        self.key_prefix = key_prefix
        self._max_connections = max_connections
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._service: CacheService | None = None

    async def service(self) -> CacheService | None:
        """None while Redis is unreachable; the next call tries again."""
        if self._service is None:
            try:
                adapter = await CacheProviderFactory.create_and_initialize(
                    provider="standard",
                    redis_url=self._redis_url,
                    max_connections=self._max_connections,
                    socket_timeout=self._socket_timeout,
                    socket_connect_timeout=self._socket_connect_timeout,
                )
            except Exception:
                logger.warning(
                    "Cache unavailable; caching is off until Redis answers", exc_info=True
                )
                return None
            self._service = CacheService(cache=adapter, key_prefix=self.key_prefix)
        return self._service

    async def client(self) -> "Redis | None":
        service = await self.service()
        return cast("Redis | None", service.cache.client) if service else None

    async def close(self) -> None:
        service, self._service = self._service, None
        if service is not None:
            await service.cache.close()
