"""Cache exceptions for the provider-agnostic cache layer."""


class CacheError(Exception):
    """Base exception for all cache-related errors."""

    pass


class CacheConnectionError(CacheError):
    """Raised when unable to connect to the cache provider."""

    pass


class CacheOperationError(CacheError):
    """Raised when a cache operation fails."""

    pass


class CacheTimeoutError(CacheError):
    """Raised when a cache operation times out."""

    pass
