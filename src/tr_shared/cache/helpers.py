"""
Stateless cache helper utilities.

Provides standardized cache key generation and pattern-based invalidation
that work with any CacheInterface implementation.
"""

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tr_shared.cache.interface import CacheInterface

logger = logging.getLogger(__name__)


def build_cache_key(*parts: Any, prefix: str) -> str:
    """Build a standardized cache key.

    Format: ``{prefix}:{part1}:{part2}:...``

    Args:
        *parts: Variable key segments.
        prefix: Key prefix (e.g. ``"dev:myservice"``).

    Returns:
        Formatted cache key string.

    Example::

        >>> build_cache_key("listings", "123", prefix="dev:listing")
        'dev:listing:listings:123'
    """
    cleaned = [str(p) for p in parts if p is not None]
    return ":".join([prefix, *cleaned])


def build_entity_cache_key(
    entity: str,
    identifier: Any,
    tenant_id: str | None = None,
    *,
    prefix: str,
) -> str:
    """Build cache key for a single entity.

    Args:
        entity: Entity name (e.g. ``"listings"``).
        identifier: Entity ID or slug.
        tenant_id: Optional tenant ID for multi-tenant isolation.
        prefix: Key prefix.
    """
    if tenant_id:
        return build_cache_key(entity, tenant_id, identifier, prefix=prefix)
    return build_cache_key(entity, identifier, prefix=prefix)


def build_list_cache_key(
    entity: str,
    filters: dict | None = None,
    *,
    prefix: str,
    **kwargs: Any,
) -> str:
    """Build cache key for list queries with optional filter hash.

    Args:
        entity: Entity name.
        filters: Filter dictionary.
        prefix: Key prefix.
        **kwargs: Additional filter parameters merged into *filters*.
    """
    import hashlib

    all_filters = {**(filters or {}), **kwargs}

    if not all_filters:
        return build_cache_key(entity, "list", "all", prefix=prefix)

    filter_str = json.dumps(all_filters, sort_keys=True)
    filter_hash = hashlib.sha256(filter_str.encode()).hexdigest()[:8]
    return build_cache_key(entity, "list", f"hash_{filter_hash}", prefix=prefix)


async def invalidate_pattern(cache: "CacheInterface", pattern: str) -> int:
    """Delete all keys matching *pattern* via SCAN.

    Args:
        cache: CacheInterface instance.
        pattern: Glob pattern (e.g. ``"dev:cms:blogs:*"``).

    Returns:
        Number of keys deleted.
    """
    deleted_count = 0
    try:
        cursor = 0
        while True:
            cursor, keys = await cache.scan(
                cursor=cursor, match=pattern, count=100
            )
            if keys:
                deleted_count += await cache.delete(*keys)
            if cursor == 0:
                break
        logger.info(
            "Invalidated %d keys matching pattern: %s", deleted_count, pattern
        )
    except Exception as e:
        logger.warning("Error invalidating cache pattern %s: %s", pattern, e)
    return deleted_count


async def invalidate_entity_cache(
    cache: "CacheInterface",
    entity: str,
    identifier: Any | None = None,
    tenant_id: str | None = None,
    *,
    prefix: str,
) -> int:
    """Invalidate cache for an entity or all entities of a type.

    Args:
        cache: CacheInterface instance.
        entity: Entity name.
        identifier: Optional entity ID. If ``None``, invalidates all.
        tenant_id: Optional tenant ID.
        prefix: Key prefix.
    """
    if identifier:
        key = build_entity_cache_key(
            entity, identifier, tenant_id, prefix=prefix
        )
        deleted = await cache.delete(key)
        logger.info("Invalidated cache for %s:%s", entity, identifier)
        return deleted

    if tenant_id:
        pattern = build_cache_key(entity, tenant_id, "*", prefix=prefix)
    else:
        pattern = build_cache_key(entity, "*", prefix=prefix)
    return await invalidate_pattern(cache, pattern)


async def invalidate_list_caches(
    cache: "CacheInterface", entity: str, *, prefix: str
) -> int:
    """Invalidate all list caches for an entity type.

    Args:
        cache: CacheInterface instance.
        entity: Entity name.
        prefix: Key prefix.
    """
    pattern = build_cache_key(entity, "list", "*", prefix=prefix)
    return await invalidate_pattern(cache, pattern)
