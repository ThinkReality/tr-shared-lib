"""Shared health check router for all ThinkRealty services."""

from tr_shared.health.router import create_health_router
from tr_shared.health.schemas import (
    ComponentCheck,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)

__all__ = [
    "create_health_router",
    "ComponentCheck",
    "HealthResponse",
    "LivenessResponse",
    "ReadinessResponse",
]
