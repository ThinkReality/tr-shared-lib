"""Pydantic models and enums for the shared rate limiter."""

from enum import Enum

from pydantic import BaseModel, Field


class Algorithm(str, Enum):
    """Rate limiting algorithm."""

    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"


class FailMode(str, Enum):
    """Behavior when Redis is unavailable."""

    OPEN = "open"  # Allow requests (default — most services)
    CLOSED = "closed"  # Block requests (gateway auth endpoints)


class WindowConfig(BaseModel):
    """Configuration for a single rate-limit window."""

    limit: int = Field(
        default=100, description="Maximum requests allowed in the window"
    )
    window_seconds: int = Field(default=60, description="Window duration in seconds")


class RateLimitConfig(BaseModel):
    """Full configuration for a rate limit scope."""

    windows: list[WindowConfig] = Field(default_factory=lambda: [WindowConfig()])
    algorithm: Algorithm = Algorithm.FIXED_WINDOW
    fail_mode: FailMode = FailMode.OPEN
    key_prefix: str = Field(default="rl", description="Redis key prefix for this scope")
    methods: list[str] | None = Field(
        default=None,
        description='HTTP methods to rate-limit. None = all; ["POST","PUT","PATCH","DELETE"] = writes only',
    )


class RateLimitResult(BaseModel):
    """Result of checking a single rate-limit window."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: int = Field(description="Unix timestamp when the window resets")
    retry_after: int = Field(
        default=0, description="Seconds until the client may retry"
    )


class RateLimitInfo(BaseModel):
    """Aggregated result across all configured windows."""

    results: list[RateLimitResult] = Field(default_factory=list)
    is_blocked: bool = False
