"""
Standard Redis Adapter — implementation for local/Docker Redis.

Wraps the standard redis-py library to implement the CacheInterface.
Used for local development and any environment with a standard Redis instance.

Only the provider-specific methods are implemented here; all shared behaviour
is inherited from BaseRedisAdapter.
"""

import logging
from typing import Any

from redis.asyncio import ConnectionPool, Redis

from tr_shared.cache.adapters.base import BaseRedisAdapter
from tr_shared.cache.exceptions import CacheConnectionError, CacheOperationError
from tr_shared.cache.interface import PipelineInterface

logger = logging.getLogger(__name__)


class StandardPipeline(PipelineInterface):
    """Pipeline implementation for Standard Redis."""

    def __init__(self, redis_client: Redis) -> None:
        self._client = redis_client
        self._pipe = None

    def _get_pipe(self):
        if self._pipe is None:
            self._pipe = self._client.pipeline()
        return self._pipe

    def setex(self, key: str, ttl: int, value: str) -> "PipelineInterface":
        """Add SETEX command to pipeline."""
        self._get_pipe().setex(key, ttl, value)
        return self

    async def execute(self) -> list[Any]:
        """Execute all commands in pipeline."""
        if self._pipe is None:
            return []
        return await self._pipe.execute()


class StandardRedisAdapter(BaseRedisAdapter):
    """Standard Redis adapter implementing CacheInterface.

    Wraps redis-py to provide a provider-agnostic interface
    for local development and standard Redis deployments.
    """

    def __init__(
        self,
        url: str,
        max_connections: int = 50,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
    ) -> None:
        self._url = url
        self._max_connections = max_connections
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None
        self._available = False

    async def initialize(self) -> bool:
        """Initialize Redis connection."""
        try:
            self._pool = ConnectionPool.from_url(
                self._url,
                max_connections=self._max_connections,
                decode_responses=True,
                socket_timeout=self._socket_timeout,
                socket_connect_timeout=self._socket_connect_timeout,
            )
            self._client = Redis(connection_pool=self._pool)
            await self._client.ping()
            self._available = True
            logger.info("Standard Redis connection initialized successfully")
            return True
        except Exception as e:
            self._available = False
            logger.warning("Standard Redis connection failed: %s", e)
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._pool:
            try:
                await self._pool.disconnect()
                logger.info("Standard Redis connection pool closed")
            except Exception as e:
                logger.warning("Error closing Redis connection: %s", e)
            finally:
                self._pool = None
                self._client = None
                self._available = False

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        if not self._client or not self._available:
            return False
        try:
            return await self._client.ping()
        except Exception:
            return False

    async def set(
        self, key: str, value: str, ttl: int | None = None, nx: bool = False
    ) -> bool:
        """Set key to value.

        Uses a single atomic ``SET key value EX ttl NX`` call where possible,
        which is more efficient than separate SETNX + EXPIRE.
        """
        self._check_initialized("set")
        try:
            kwargs: dict[str, Any] = {}
            if ttl is not None:
                kwargs["ex"] = ttl
            if nx:
                kwargs["nx"] = True
            result = await self._client.set(key, value, **kwargs)
            return result is not None
        except Exception as e:
            raise CacheOperationError(f"SET failed: {e}") from e

    async def xadd(
        self, stream: str, fields: dict[str, str], maxlen: int | None = None
    ) -> str | None:
        self._check_initialized("xadd")
        try:
            kwargs: dict[str, Any] = {}
            if maxlen is not None:
                kwargs["maxlen"] = maxlen
            return await self._client.xadd(stream, fields, **kwargs)
        except Exception as e:
            raise CacheOperationError(f"XADD failed: {e}") from e

    def pipeline(self) -> PipelineInterface:
        if not self._client:
            raise CacheConnectionError("Redis not initialized")
        return StandardPipeline(self._client)
