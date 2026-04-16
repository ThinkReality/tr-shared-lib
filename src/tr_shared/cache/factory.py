"""Cache provider factory — config-driven adapter selection."""

import logging
from enum import Enum
from typing import TYPE_CHECKING

from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.cache.exceptions import CacheConnectionError

try:
    from tr_shared.cache.adapters.upstash import UpstashAdapter as _UpstashAdapter
    _UPSTASH_AVAILABLE = True
except ImportError:
    _UpstashAdapter = None  # type: ignore[assignment]
    _UPSTASH_AVAILABLE = False

if TYPE_CHECKING:
    from tr_shared.cache.interface import CacheInterface

logger = logging.getLogger(__name__)


class CacheProvider(str, Enum):
    """Supported cache providers."""

    STANDARD = "standard"
    UPSTASH = "upstash"


class CacheProviderFactory:
    """Factory for creating cache provider instances.

    Unlike the CMS-local factory, this version accepts parameters directly
    instead of reading from a settings object, making it service-agnostic.
    """

    @staticmethod
    def create(
        provider: str = "standard",
        # Standard Redis params
        redis_url: str = "redis://localhost:6379/0",
        max_connections: int = 50,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
        # Upstash params
        upstash_rest_url: str = "",
        upstash_rest_token: str = "",
        upstash_read_your_writes: bool = True,
    ) -> "CacheInterface":
        """Create the appropriate cache provider instance.

        Args:
            provider: "standard" or "upstash".
            redis_url: Redis connection URL (standard provider).
            max_connections: Max pool size (standard provider).
            socket_timeout: Socket timeout seconds (standard provider).
            socket_connect_timeout: Connect timeout seconds (standard provider).
            upstash_rest_url: Upstash REST endpoint (upstash provider).
            upstash_rest_token: Upstash API token (upstash provider).
            upstash_read_your_writes: Consistency flag (upstash provider).

        Returns:
            CacheInterface implementation instance.
        """
        provider_lower = provider.lower()
        logger.info("Initializing cache provider: %s", provider_lower)

        if provider_lower == CacheProvider.UPSTASH:
            if not _UPSTASH_AVAILABLE:
                raise ImportError(
                    "upstash-redis is required for the upstash provider. "
                    "Install it with: pip install tr-shared-lib[upstash]"
                )
            return _UpstashAdapter(
                rest_url=upstash_rest_url,
                rest_token=upstash_rest_token,
                read_your_writes=upstash_read_your_writes,
            )

        if provider_lower == CacheProvider.STANDARD:
            return StandardRedisAdapter(
                url=redis_url,
                max_connections=max_connections,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
            )

        raise ValueError(
            f"Unsupported cache provider: {provider}. "
            f"Use one of: {[p.value for p in CacheProvider]}"
        )

    @staticmethod
    async def create_and_initialize(**kwargs) -> "CacheInterface":
        """Create cache provider and initialize connection.

        Raises:
            CacheConnectionError: If the adapter fails to initialize
                (e.g., Redis unreachable, DNS failure, auth error).
        """
        cache = CacheProviderFactory.create(**kwargs)
        success = await cache.initialize()
        if not success:
            raise CacheConnectionError(
                "Cache adapter failed to initialize — Redis may be unreachable"
            )
        return cache
