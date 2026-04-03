"""Shared cache abstraction: provider-agnostic interface, adapters, factory, and service."""

from tr_shared.cache.exceptions import (
    CacheConnectionError,
    CacheError,
    CacheOperationError,
    CacheTimeoutError,
)
from tr_shared.cache.factory import CacheProvider, CacheProviderFactory
from tr_shared.cache.interface import CacheInterface, PipelineInterface
from tr_shared.cache.service import CacheService

__all__ = [
    "CacheConnectionError",
    "CacheError",
    "CacheInterface",
    "CacheOperationError",
    "CacheProvider",
    "CacheProviderFactory",
    "CacheService",
    "CacheTimeoutError",
    "PipelineInterface",
]
