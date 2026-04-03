"""Shared rate limiter for ThinkRealty microservices.

Provides Redis-backed rate limiting with:
- Fixed window and sliding window algorithms
- Multi-window support (e.g. 100/min AND 1000/hour)
- Fail-open and fail-closed modes
- In-memory fallback when Redis is unavailable
- Middleware, FastAPI dependency, and decorator usage patterns
"""

from tr_shared.rate_limiter.core import RateLimiter, default_identifier_extractor
from tr_shared.rate_limiter.dependency import create_rate_limit_dependency, rate_limit
from tr_shared.rate_limiter.exceptions import RateLimitExceeded
from tr_shared.rate_limiter.memory_fallback import MemoryFallback
from tr_shared.rate_limiter.middleware import RateLimitMiddleware
from tr_shared.rate_limiter.schemas import (
    Algorithm,
    FailMode,
    RateLimitConfig,
    RateLimitInfo,
    RateLimitResult,
    WindowConfig,
)

__all__ = [
    # Core
    "RateLimiter",
    "default_identifier_extractor",
    "RateLimitMiddleware",
    "MemoryFallback",
    # Dependency + decorator
    "create_rate_limit_dependency",
    "rate_limit",
    # Schemas + enums
    "Algorithm",
    "FailMode",
    "RateLimitConfig",
    "RateLimitExceeded",
    "RateLimitInfo",
    "RateLimitResult",
    "WindowConfig",
]
