"""
High-level cache service with JSON serialization, key building, and pattern invalidation.

Usage::

    from tr_shared.cache import CacheProviderFactory, CacheService

    cache = await CacheProviderFactory.create_and_initialize(
        provider="standard", redis_url="redis://localhost:6379/0"
    )
    svc = CacheService(cache=cache, key_prefix="dev:myservice")

    await svc.set("listings:123", {"name": "..."}, ttl=3600)
    data = await svc.get("listings:123")
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from tr_shared.cache.interface import CacheInterface

JSONType = dict | list | str | int | float | bool | None

logger = logging.getLogger(__name__)


@dataclass
class CacheResult:
    """Typed result from :meth:`CacheService.get_result`.

    Allows callers to distinguish between a cache miss (``hit=False``,
    ``error=None``) and a Redis failure (``hit=False``, ``error`` set).

    Attributes:
        value: Deserialized cached value, or ``None`` on miss/error.
        hit: ``True`` if the key was found in cache.
        error: The exception if a Redis error occurred, else ``None``.
    """

    value: JSONType | None
    hit: bool
    error: Exception | None = field(default=None)


class CacheService:
    """Injectable cache service backed by CacheInterface.

    All methods use silent-fail semantics: errors are logged and a safe
    default (None / 0 / {}) is returned instead of raising.

    Args:
        cache: A CacheInterface implementation (from factory or DI).
        key_prefix: Prefix prepended to all keys built via :meth:`build_key`.
            Typically ``"{environment}:{service_name}"``.
        max_value_bytes: Maximum serialized value size for :meth:`set`.
            Rejects payloads exceeding this limit with a ``ValueError``.
            Defaults to 1 MB. Set to 0 to disable the check.
    """

    DEFAULT_MAX_VALUE_BYTES = 1_048_576  # 1 MB

    def __init__(
        self,
        cache: "CacheInterface",
        key_prefix: str,
        max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES,
    ) -> None:
        self.cache = cache
        self.key_prefix = key_prefix
        self._max_value_bytes = max_value_bytes

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get(self, key: str) -> JSONType | None:
        """Get JSON-deserialized value from cache."""
        try:
            cached = await self.cache.get(key)
            if cached is not None:
                logger.debug("Cache hit: %s", key, extra={"cache_status": "hit", "key": key})
                return json.loads(cached)
            logger.debug("Cache miss: %s", key, extra={"cache_status": "miss", "key": key})
        except Exception as e:
            logger.error("Cache get error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
        return None

    async def get_result(self, key: str) -> CacheResult:
        """Get a typed result that distinguishes hit, miss, and error.

        Unlike :meth:`get`, callers can inspect ``result.hit`` and
        ``result.error`` to tell apart a cache miss from a Redis failure::

            result = await svc.get_result("listings:123")
            if result.error:
                # Redis is down — fall back to DB
            elif result.hit:
                return result.value   # from cache
            else:
                # genuine miss — fetch from DB and cache
        """
        try:
            cached = await self.cache.get(key)
            if cached is not None:
                logger.debug("Cache hit: %s", key, extra={"cache_status": "hit", "key": key})
                return CacheResult(value=json.loads(cached), hit=True)
            logger.debug("Cache miss: %s", key, extra={"cache_status": "miss", "key": key})
            return CacheResult(value=None, hit=False)
        except Exception as e:
            logger.error(
                "Cache get error for key %s: %s", key, e,
                extra={"cache_status": "error", "key": key},
            )
            return CacheResult(value=None, hit=False, error=e)

    async def get_many(self, keys: list[str]) -> dict[str, JSONType | None]:
        """Get JSON-deserialized values for multiple keys."""
        if not keys:
            return {}
        try:
            cached_values = await self.cache.mget(keys)
            result: dict[str, JSONType | None] = {}
            for key, cached in zip(keys, cached_values, strict=False):
                if cached is None:
                    result[key] = None
                    continue
                result[key] = json.loads(cached)
            return result
        except Exception as e:
            logger.error("Cache mget error for %d keys: %s", len(keys), e, extra={"cache_status": "error"})
            return dict.fromkeys(keys)

    async def get_or_set(
        self,
        key: str,
        fetch_func: Callable[..., Coroutine[Any, Any, Any]],
        ttl: int = 3600,
        **fetch_kwargs: Any,
    ) -> Any:
        """Cache-aside: return cached value or fetch, cache, and return.

        On any cache error the fetch function is called directly as fallback.
        """
        try:
            cached = await self.cache.get(key)
            if cached is not None:
                logger.debug("Cache hit: %s", key)
                return json.loads(cached)

            logger.debug("Cache miss: %s", key)
            data = await fetch_func(**fetch_kwargs)

            if data is not None:
                await self.cache.setex(
                    key, ttl, json.dumps(data, default=str)
                )
            return data
        except Exception as e:
            logger.error("Cache error for %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return await fetch_func(**fetch_kwargs)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Serialize value to JSON and store with TTL.

        Raises:
            ValueError: If serialized payload exceeds ``max_value_bytes``.
        """
        try:
            serialized = json.dumps(value, default=str)
            if self._max_value_bytes and len(serialized.encode()) > self._max_value_bytes:
                raise ValueError(
                    f"Cache value for '{key}' is {len(serialized.encode())} bytes, "
                    f"exceeds limit of {self._max_value_bytes} bytes"
                )
            await self.cache.setex(key, ttl, serialized)
            logger.debug("Cached key: %s (TTL: %ds)", key, ttl)
        except ValueError:
            raise
        except Exception as e:
            logger.error("Cache set error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})

    async def set_many(self, items: dict[str, Any], ttl: int = 3600) -> int:
        """Serialize and cache multiple key-value pairs via pipeline."""
        if not items:
            return 0
        try:
            pipe = self.cache.pipeline()
            for key, value in items.items():
                pipe.setex(key, ttl, json.dumps(value, default=str))
            await pipe.execute()
            logger.debug("Cached %d keys (TTL: %ds)", len(items), ttl)
            return len(items)
        except Exception as e:
            logger.error(
                "Cache set_many error for %d keys: %s", len(items), e,
                extra={"cache_status": "error"},
            )
            return 0

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, *keys: str) -> None:
        """Delete one or more cache keys."""
        if not keys:
            return
        try:
            await self.cache.delete(*keys)
            logger.debug("Invalidated cache keys: %s", ", ".join(keys))
        except Exception as e:
            logger.error("Cache delete error: %s", e, extra={"cache_status": "error"})

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob pattern via SCAN."""
        try:
            deleted_count = 0
            cursor = 0
            while True:
                cursor, keys = await self.cache.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    deleted_count += await self.cache.delete(*keys)
                if cursor == 0:
                    break
            logger.info(
                "Invalidated %d keys matching pattern: %s",
                deleted_count,
                pattern,
            )
            return deleted_count
        except Exception as e:
            logger.error(
                "Cache pattern delete error for %s: %s", pattern, e,
                extra={"cache_status": "error"},
            )
            return 0

    # ------------------------------------------------------------------
    # Atomic counter / existence check
    # ------------------------------------------------------------------

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Atomically increment a counter. Optionally set TTL on first creation.

        TTL is applied only when ``amount`` creates the key (i.e. new_value == amount),
        preventing accidental TTL resets on subsequent increments.

        Returns:
            New counter value, or 0 on error (silent-fail).
        """
        try:
            new_val = await self.cache.incrby(key, amount)
            if ttl is not None and new_val == amount:
                await self.cache.expire(key, ttl)
            return new_val
        except Exception as e:
            logger.error("Cache increment error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return 0

    async def exists(self, key: str) -> bool:
        """Return True if key exists in cache."""
        try:
            return bool(await self.cache.exists(key))
        except Exception as e:
            logger.error("Cache exists error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return False

    async def ttl(self, key: str) -> int:
        """Return remaining TTL in seconds for a key.

        Returns:
            Remaining TTL (≥0), -1 if key has no expiry, -2 if key does not exist.
            Returns -2 on error (silent-fail).
        """
        try:
            return await self.cache.ttl(key)
        except Exception as e:
            logger.error("Cache ttl error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return -2

    async def expire(self, key: str, seconds: int) -> bool:
        """Reset the TTL on an existing key without rewriting the value.

        Returns:
            True if the timeout was set, False if the key does not exist.
            Returns False on error (silent-fail).
        """
        try:
            return await self.cache.expire(key, seconds)
        except Exception as e:
            logger.error("Cache expire error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return False

    async def scan_keys(self, pattern: str, count: int = 100) -> list[str]:
        """Collect all keys matching a glob pattern via cursor-based SCAN.

        Iterates until the SCAN cursor returns to 0. Safe for large keyspaces.
        Use instead of manual SCAN loops in service code.

        Returns:
            All matching key names. Returns [] on error (silent-fail).
        """
        try:
            keys: list[str] = []
            cursor = 0
            while True:
                cursor, batch = await self.cache.scan(
                    cursor=cursor, match=pattern, count=count
                )
                keys.extend(batch)
                if cursor == 0:
                    break
            return keys
        except Exception as e:
            logger.error("Cache scan_keys error for pattern %s: %s", pattern, e, extra={"cache_status": "error"})
            return []

    # ------------------------------------------------------------------
    # Sorted-set operations
    # ------------------------------------------------------------------

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        """Add/update members with scores in a sorted set.

        Args:
            key: Sorted-set key.
            mapping: ``{member: score}`` dict. Members are stored as strings.

        Returns:
            Number of NEW members added (existing members are updated in-place).
            Returns 0 on error (silent-fail).
        """
        try:
            return await self.cache.zadd(key, mapping)
        except Exception as e:
            logger.error("Cache zadd error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return 0

    async def zrangebyscore(
        self,
        key: str,
        min: float | str,
        max: float | str,
        *,
        withscores: bool = False,
    ) -> list:
        """Return members from a sorted set within a score range.

        Args:
            key: Sorted-set key.
            min: Lower bound (inclusive). Use ``"-inf"`` for unbounded.
            max: Upper bound (inclusive). Use ``"+inf"`` for unbounded.
            withscores: If True, returns ``[(member, score), ...]`` tuples.

        Returns:
            List of members (or tuples when withscores=True).
            Returns [] on error (silent-fail).
        """
        try:
            return await self.cache.zrangebyscore(key, min, max, withscores=withscores)
        except Exception as e:
            logger.error("Cache zrangebyscore error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return []

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        """Return members from a sorted set by ascending rank index.

        Args:
            key: Sorted-set key.
            start: Start rank (0-based, inclusive).
            end: End rank (inclusive). Use -1 for the last element.

        Returns:
            List of member strings. Returns [] on error (silent-fail).
        """
        try:
            return await self.cache.zrange(key, start, end)
        except Exception as e:
            logger.error("Cache zrange error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return []

    async def zrem(self, key: str, *members: str) -> int:
        """Remove one or more members from a sorted set.

        Returns:
            Number of members removed. Returns 0 on error (silent-fail).
        """
        try:
            return await self.cache.zrem(key, *members)
        except Exception as e:
            logger.error("Cache zrem error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return 0

    # ------------------------------------------------------------------
    # Set operations
    # ------------------------------------------------------------------

    async def sadd(self, key: str, *members: str) -> int:
        """Add one or more members to a Redis set.

        Returns:
            Number of new members added (duplicates are silently ignored).
            Returns 0 on error (silent-fail).
        """
        try:
            return await self.cache.sadd(key, *members)
        except Exception as e:
            logger.error("Cache sadd error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return 0

    async def srem(self, key: str, *members: str) -> int:
        """Remove one or more members from a Redis set.

        Returns:
            Number of members removed. Returns 0 on error (silent-fail).
        """
        try:
            return await self.cache.srem(key, *members)
        except Exception as e:
            logger.error("Cache srem error for key %s: %s", key, e, extra={"cache_status": "error", "key": key})
            return 0

    # ------------------------------------------------------------------
    # Key building
    # ------------------------------------------------------------------

    def build_key(self, *parts: Any) -> str:
        """Build a cache key using the standard prefix."""
        clean_parts = [str(part) for part in parts if part is not None]
        return ":".join([self.key_prefix, *clean_parts])

    def build_list_key(
        self, entity: str, filters: dict | None = None
    ) -> str:
        """Build a cache key for list queries with filter hash."""
        if not filters:
            return self.build_key(entity, "list", "all")
        filter_hash = hashlib.sha256(
            json.dumps(filters, sort_keys=True).encode()
        ).hexdigest()[:8]
        return self.build_key(entity, "list", f"hash_{filter_hash}")
