"""Shared health router factory for all ThinkRealty services."""

import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from tr_shared.health.schemas import (
    ComponentCheck,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)


def create_health_router(
    service_name: str,
    version: str = "1.0.0",
    db_check: Callable[[], Awaitable[bool]] | None = None,
    redis_check: Callable[[], Awaitable[bool]] | None = None,
) -> APIRouter:
    """Create a standard health router with liveness, readiness, and live endpoints."""
    router = APIRouter()

    @router.get(
        "",
        response_model=HealthResponse,
        summary="Health check",
        description="Basic liveness check — returns 200 if the process is running.",
    )
    async def health() -> HealthResponse:
        return HealthResponse(status="healthy", service=service_name, version=version)

    @router.get(
        "/ready",
        summary="Readiness probe",
        description="Checks critical dependencies (DB, Redis). Returns 503 if any are down.",
        responses={
            200: {"model": ReadinessResponse, "description": "Service ready"},
            503: {"model": ReadinessResponse, "description": "Service not ready"},
        },
    )
    async def readiness() -> JSONResponse:
        checks: dict[str, bool] = {}
        details: list[ComponentCheck] = []

        for name, check_fn in [("database", db_check), ("redis", redis_check)]:
            if check_fn is None:
                continue
            start = time.monotonic()
            try:
                healthy = await check_fn()
                latency = round((time.monotonic() - start) * 1000, 2)
                checks[name] = healthy
                details.append(ComponentCheck(name=name, healthy=healthy, latency_ms=latency))
            except Exception as exc:
                latency = round((time.monotonic() - start) * 1000, 2)
                checks[name] = False
                details.append(
                    ComponentCheck(name=name, healthy=False, latency_ms=latency, error=str(exc))
                )

        all_healthy = all(checks.values()) if checks else True
        status_str = "ready" if all_healthy else "not_ready"
        status_code = 200 if all_healthy else 503

        body = ReadinessResponse(
            status=status_str, service=service_name, checks=checks, details=details
        )
        return JSONResponse(content=body.model_dump(mode="json"), status_code=status_code)

    @router.get(
        "/live",
        response_model=LivenessResponse,
        summary="Liveness probe",
        description="Minimal probe — returns 200 if the process is alive.",
    )
    async def liveness() -> LivenessResponse:
        return LivenessResponse(status="alive")

    return router
