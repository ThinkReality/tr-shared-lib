"""Standard health check response schemas for all ThinkRealty services."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Basic health/liveness response."""

    status: str = Field(description="Service health status", examples=["healthy"])
    service: str = Field(description="Service name")
    version: str = Field(description="Service version")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Response timestamp")


class ComponentCheck(BaseModel):
    """Result of a single dependency check (DB, Redis, etc.)."""

    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness probe response with dependency checks."""

    status: str = Field(description="'ready' or 'not_ready'", examples=["ready"])
    service: str
    checks: dict[str, bool] = Field(
        default_factory=dict, description="Component → healthy status"
    )
    details: list[ComponentCheck] = Field(
        default_factory=list, description="Detailed per-component results"
    )


class LivenessResponse(BaseModel):
    """Minimal liveness probe response."""

    status: str = Field(default="alive", description="Always 'alive' if process is running")
