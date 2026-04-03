"""Cache adapters package."""

from tr_shared.cache.adapters.base import BaseRedisAdapter
from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter

__all__ = ["BaseRedisAdapter", "StandardRedisAdapter"]

# UpstashAdapter is imported lazily by the factory when needed.
