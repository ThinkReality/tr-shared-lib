"""
Upstash Redis Adapter — implementation for Upstash Serverless Redis.

Uses the upstash-redis Python SDK to connect via REST API.
Used for production environments where serverless Redis is preferred.

Only the provider-specific methods are implemented here; all shared behaviour
is inherited from BaseRedisAdapter.

Requires the ``upstash`` extra: ``pip install tr-shared-lib[upstash]``
"""

import logging
from typing import Any

try:
    from upstash_redis.asyncio import Redis as AsyncUpstashRedis
    from upstash_redis.asyncio.client import AsyncPipeline
except ImportError as exc:
    raise ImportError(
        "upstash-redis is required for UpstashAdapter. "
        "Install it with: pip install tr-shared-lib[upstash]"
    ) from exc

from tr_shared.cache.adapters.base import BaseRedisAdapter
from tr_shared.cache.exceptions import CacheConnectionError, CacheOperationError
from tr_shared.cache.interface import PipelineInterface

logger = logging.getLogger(__name__)


class UpstashPipeline(PipelineInterface):
    """Pipeline implementation for Upstash Redis.

    Delegates to the native upstash-redis AsyncPipeline, which batches
    all queued commands into a single HTTP request on exec().
    """

    def __init__(self, pipe: AsyncPipeline) -> None:
        self._pipe = pipe

    def setex(self, key: str, ttl: int, value: str) -> "PipelineInterface":
        self._pipe.setex(key, ttl, value)
        return self

    async def execute(self) -> list[Any]:
        """Flush all queued commands as a single batched HTTP request."""
        return await self._pipe.exec()


class UpstashAdapter(BaseRedisAdapter):
    """Upstash Redis adapter implementing CacheInterface.

    Uses the upstash-redis SDK to provide a provider-agnostic interface
    for Upstash serverless Redis via HTTP/REST API.
    """

    def __init__(
        self,
        rest_url: str,
        rest_token: str,
        read_your_writes: bool = True,
    ) -> None:
        self._rest_url = rest_url
        self._rest_token = rest_token
        self._read_your_writes = read_your_writes
        self._client: AsyncUpstashRedis | None = None
        self._available = False

    async def initialize(self) -> bool:
        try:
            self._client = AsyncUpstashRedis(
                url=self._rest_url,
                token=self._rest_token,
                read_your_writes=self._read_your_writes,
            )
            await self._client.ping()
            self._available = True
            logger.info("Upstash Redis connection initialized successfully")
            return True
        except Exception as e:
            self._available = False
            logger.warning("Upstash Redis connection failed: %s", e)
            return False

    async def close(self) -> None:
        """Close Upstash connection (no-op for REST API)."""
        self._client = None
        self._available = False
        logger.info("Upstash Redis connection closed")

    async def ping(self) -> bool:
        if not self._client or not self._available:
            return False
        try:
            result = await self._client.ping()
            return result == "PONG"
        except Exception:
            return False

    async def set(
        self, key: str, value: str, ttl: int | None = None, nx: bool = False
    ) -> bool:
        """Set key to value.

        When ``nx=True``, uses a single atomic SET NX EX command so the key
        either gets both the value and TTL or is not written at all. This
        prevents a permanently-live key if the process crashes between a
        SETNX and EXPIRE pair.
        """
        self._check_initialized("set")
        try:
            if nx:
                # upstash-redis supports set(nx=True, ex=ttl) same as redis-py;
                # returns the stored value on success, None on miss.
                result = await self._client.set(key, value, nx=True, ex=ttl)
                return result is not None
            elif ttl:
                result = await self._client.setex(key, ttl, value)
                return result is not None
            else:
                result = await self._client.set(key, value)
                return result is not None
        except Exception as e:
            raise CacheOperationError(f"SET failed: {e}") from e

    async def xadd(
        self, stream: str, fields: dict[str, str], maxlen: int | None = None
    ) -> str | None:
        """Append an entry to a stream.

        Uses ``approximate=True`` for Upstash REST API stream trimming efficiency.
        """
        self._check_initialized("xadd")
        try:
            return await self._client.xadd(
                stream, fields, maxlen=maxlen, approximate=True
            )
        except Exception as e:
            raise CacheOperationError(f"XADD failed: {e}") from e

    def pipeline(self) -> PipelineInterface:
        if not self._client:
            raise CacheConnectionError("Upstash not initialized")
        return UpstashPipeline(self._client.pipeline())
