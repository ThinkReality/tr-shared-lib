"""
Abstract base classes for the cache abstraction layer.

Defines the contracts that all cache adapters must implement,
ensuring the rest of the application is decoupled from any
specific cache provider (Redis, Upstash, etc.).
"""

from abc import ABC, abstractmethod
from typing import Any


class PipelineInterface(ABC):
    """Abstract base for batched cache operations."""

    @abstractmethod
    def setex(self, key: str, ttl: int, value: str) -> "PipelineInterface":
        """Queue a SETEX command."""
        ...

    @abstractmethod
    async def execute(self) -> list[Any]:
        """Execute all queued commands and return results."""
        ...


class CacheInterface(ABC):
    """Abstract base for all cache provider adapters."""

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the connection. Returns True on success."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the connection and release resources."""
        ...

    @abstractmethod
    async def ping(self) -> bool:
        """Return True if the cache is reachable."""
        ...

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Return the value for key, or None if not found."""
        ...

    @abstractmethod
    async def set(
        self, key: str, value: str, ttl: int | None = None, nx: bool = False
    ) -> bool:
        """Set key to value. Returns True on success."""
        ...

    @abstractmethod
    async def setex(self, key: str, ttl: int, value: str) -> bool:
        """Set key to value with an expiration in seconds."""
        ...

    @abstractmethod
    async def delete(self, *keys: str) -> int:
        """Delete one or more keys. Returns number of keys deleted."""
        ...

    @abstractmethod
    async def exists(self, *keys: str) -> int:
        """Return the number of given keys that exist."""
        ...

    @abstractmethod
    async def ttl(self, key: str) -> int:
        """Return the remaining TTL in seconds. -1 if no expiry, -2 if missing."""
        ...

    @abstractmethod
    async def expire(self, key: str, seconds: int) -> bool:
        """Set a timeout on key. Returns True if the timeout was set."""
        ...

    @abstractmethod
    async def mget(self, keys: list[str]) -> list[str | None]:
        """Return values for all given keys in order."""
        ...

    @abstractmethod
    async def hgetall(self, key: str) -> dict[str, str]:
        """Return all fields and values in a hash."""
        ...

    @abstractmethod
    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        """Set multiple hash fields. Returns number of fields added."""
        ...

    @abstractmethod
    async def xadd(
        self, stream: str, fields: dict[str, str], maxlen: int | None = None
    ) -> str | None:
        """Append an entry to a stream. Returns the entry ID."""
        ...

    @abstractmethod
    async def incrby(self, key: str, amount: int) -> int:
        """Increment key by amount. Creates key with value 0 first if absent."""
        ...

    @abstractmethod
    async def scan(
        self, cursor: int = 0, match: str = "*", count: int = 100
    ) -> tuple[int, list[str]]:
        """Incrementally iterate keys. Returns (next_cursor, keys)."""
        ...

    @abstractmethod
    def pipeline(self) -> PipelineInterface:
        """Return a pipeline for batching multiple commands."""
        ...

    @abstractmethod
    async def eval(
        self, script: str, numkeys: int, *keys_and_args: str | int
    ) -> Any:
        """Execute a Lua script server-side."""
        ...

    # ── Sorted-set operations ──

    @abstractmethod
    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        """Add/update members with scores in a sorted set. Returns count of new members added."""
        ...

    @abstractmethod
    async def zrangebyscore(
        self, key: str, min: float | str, max: float | str, *, withscores: bool = False
    ) -> list:
        """Return members with score between min and max (inclusive).
        min/max accept floats or '-inf'/'+inf' strings."""
        ...

    @abstractmethod
    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        """Return members by ascending rank. end=-1 means last element."""
        ...

    @abstractmethod
    async def zrem(self, key: str, *members: str) -> int:
        """Remove members from sorted set. Returns count removed."""
        ...

    # ── Set operations ──

    @abstractmethod
    async def sadd(self, key: str, *members: str) -> int:
        """Add members to a set. Returns count of new members added."""
        ...

    @abstractmethod
    async def srem(self, key: str, *members: str) -> int:
        """Remove members from a set. Returns count removed."""
        ...
