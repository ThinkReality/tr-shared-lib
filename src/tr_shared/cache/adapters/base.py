"""
BaseRedisAdapter — shared implementation for all Redis-compatible adapters.

Contains the 18 methods that are identical across StandardRedisAdapter and
UpstashAdapter. Subclasses only need to implement the provider-specific
methods: ``initialize()``, ``close()``, ``ping()``, ``set()``, and ``xadd()``.

All methods follow the same two-step pattern:
  1. Guard: raise CacheConnectionError if client is not initialised.
  2. Delegate + wrap: call self._client.<op>(); on any exception raise
     CacheOperationError so callers see a provider-agnostic error type.
"""

import logging
from abc import abstractmethod
from typing import Any

from tr_shared.cache.exceptions import CacheConnectionError, CacheOperationError
from tr_shared.cache.interface import CacheInterface, PipelineInterface

logger = logging.getLogger(__name__)


class BaseRedisAdapter(CacheInterface):
    """Shared implementation base for Redis-compatible cache adapters.

    Concrete adapters (StandardRedisAdapter, UpstashAdapter) inherit this
    class and only override the provider-specific methods.
    """

    # Subclasses must assign _client before any operation is called.
    _client: Any = None
    _available: bool = False

    # ------------------------------------------------------------------
    # Provider-specific — must be implemented by each subclass
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(self) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def set(
        self, key: str, value: str, ttl: int | None = None, nx: bool = False
    ) -> bool: ...

    @abstractmethod
    async def xadd(
        self, stream: str, fields: dict[str, str], maxlen: int | None = None
    ) -> str | None: ...

    @abstractmethod
    def pipeline(self) -> PipelineInterface: ...

    # ------------------------------------------------------------------
    # Shared helper
    # ------------------------------------------------------------------

    def _check_initialized(self, op: str) -> None:
        """Raise CacheConnectionError if the client has not been initialised."""
        if not self._client or not self._available:
            raise CacheConnectionError(
                f"Cache not initialized — call initialize() before {op}()"
            )

    # ------------------------------------------------------------------
    # Shared implementations (identical across all Redis-compatible adapters)
    # ------------------------------------------------------------------

    async def get(self, key: str) -> str | None:
        self._check_initialized("get")
        try:
            return await self._client.get(key)
        except Exception as e:
            raise CacheOperationError(f"GET failed: {e}") from e

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self._check_initialized("setex")
        try:
            await self._client.setex(key, ttl, value)
            return True
        except Exception as e:
            raise CacheOperationError(f"SETEX failed: {e}") from e

    async def delete(self, *keys: str) -> int:
        self._check_initialized("delete")
        if not keys:
            return 0
        try:
            return await self._client.delete(*keys)
        except Exception as e:
            raise CacheOperationError(f"DELETE failed: {e}") from e

    async def exists(self, *keys: str) -> int:
        self._check_initialized("exists")
        if not keys:
            return 0
        try:
            return await self._client.exists(*keys)
        except Exception as e:
            raise CacheOperationError(f"EXISTS failed: {e}") from e

    async def ttl(self, key: str) -> int:
        self._check_initialized("ttl")
        try:
            return await self._client.ttl(key)
        except Exception as e:
            raise CacheOperationError(f"TTL failed: {e}") from e

    async def expire(self, key: str, seconds: int) -> bool:
        self._check_initialized("expire")
        try:
            result = await self._client.expire(key, seconds)
            return bool(result)
        except Exception as e:
            raise CacheOperationError(f"EXPIRE failed: {e}") from e

    async def mget(self, keys: list[str]) -> list[str | None]:
        self._check_initialized("mget")
        if not keys:
            return []
        try:
            return await self._client.mget(keys)
        except Exception as e:
            raise CacheOperationError(f"MGET failed: {e}") from e

    async def hgetall(self, key: str) -> dict[str, str]:
        self._check_initialized("hgetall")
        try:
            result = await self._client.hgetall(key)
            return result if result else {}
        except Exception as e:
            raise CacheOperationError(f"HGETALL failed: {e}") from e

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self._check_initialized("hset")
        try:
            return await self._client.hset(key, mapping=mapping)
        except Exception as e:
            raise CacheOperationError(f"HSET failed: {e}") from e

    async def scan(
        self, cursor: int = 0, match: str = "*", count: int = 100
    ) -> tuple[int, list[str]]:
        self._check_initialized("scan")
        try:
            return await self._client.scan(
                cursor=cursor, match=match, count=count
            )
        except Exception as e:
            raise CacheOperationError(f"SCAN failed: {e}") from e

    async def eval(
        self, script: str, numkeys: int, *keys_and_args: str | int
    ) -> Any:
        self._check_initialized("eval")
        try:
            return await self._client.eval(script, numkeys, *keys_and_args)
        except Exception as e:
            raise CacheOperationError(f"EVAL failed: {e}") from e

    async def incrby(self, key: str, amount: int) -> int:
        self._check_initialized("incrby")
        try:
            return await self._client.incrby(key, amount)
        except Exception as e:
            raise CacheOperationError(f"INCRBY failed: {e}") from e

    # ── Sorted-set operations ──

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self._check_initialized("zadd")
        try:
            return await self._client.zadd(key, mapping)
        except Exception as e:
            raise CacheOperationError(f"ZADD failed: {e}") from e

    async def zrangebyscore(
        self, key: str, min: float | str, max: float | str, *, withscores: bool = False
    ) -> list:
        self._check_initialized("zrangebyscore")
        try:
            return await self._client.zrangebyscore(key, min, max, withscores=withscores)
        except Exception as e:
            raise CacheOperationError(f"ZRANGEBYSCORE failed: {e}") from e

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        self._check_initialized("zrange")
        try:
            return await self._client.zrange(key, start, end)
        except Exception as e:
            raise CacheOperationError(f"ZRANGE failed: {e}") from e

    async def zrem(self, key: str, *members: str) -> int:
        self._check_initialized("zrem")
        try:
            return await self._client.zrem(key, *members)
        except Exception as e:
            raise CacheOperationError(f"ZREM failed: {e}") from e

    # ── Set operations ──

    async def sadd(self, key: str, *members: str) -> int:
        self._check_initialized("sadd")
        try:
            return await self._client.sadd(key, *members)
        except Exception as e:
            raise CacheOperationError(f"SADD failed: {e}") from e

    async def srem(self, key: str, *members: str) -> int:
        self._check_initialized("srem")
        try:
            return await self._client.srem(key, *members)
        except Exception as e:
            raise CacheOperationError(f"SREM failed: {e}") from e

    async def __aenter__(self) -> "CacheInterface":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
