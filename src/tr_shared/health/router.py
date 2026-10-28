"""Shared health router factory for all ThinkRealty services."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from tr_shared.contracts.db_pool import DB_CONNECT_TIMEOUT_SECONDS
from tr_shared.health.schemas import (
    ComponentCheck,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine

PROBE_TIMEOUT_SECONDS = DB_CONNECT_TIMEOUT_SECONDS + 1

logger = logging.getLogger(__name__)


async def _probe(name: str, check: Callable[[], Awaitable[None]]) -> ComponentCheck:
    started = time.monotonic()
    healthy = True
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await check()
    except Exception as exc:
        healthy = False
        logger.warning(
            "health_check_failed",
            extra={"check": name, "error_type": type(exc).__name__, "error": str(exc)},
        )
    latency_ms = round((time.monotonic() - started) * 1000, 2)
    return ComponentCheck(name=name, healthy=healthy, latency_ms=latency_ms)


def create_health_router(
    service_name: str,
    version: str = "1.0.0",
    *,
    engine: Callable[[], AsyncEngine],
    redis: Callable[[], Awaitable[Redis | None]],
) -> APIRouter:
    """Create a standard health router with liveness, readiness, and live endpoints."""
    router = APIRouter()

    async def ping_database() -> None:
        async with engine().connect() as connection:
            await connection.exec_driver_sql("SELECT 1")

    async def ping_redis() -> None:
        client = await redis()
        if client is None:
            raise ConnectionError("Redis client unavailable")
        await cast("Awaitable[bool]", client.ping())

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
        details = await asyncio.gather(
            _probe("database", ping_database), _probe("redis", ping_redis)
        )
        ready = all(detail.healthy for detail in details)
        body = ReadinessResponse(
            status="ready" if ready else "not_ready",
            service=service_name,
            checks={detail.name: detail.healthy for detail in details},
            details=list(details),
        )
        return JSONResponse(content=body.model_dump(mode="json"), status_code=200 if ready else 503)

    @router.get(
        "/live",
        response_model=LivenessResponse,
        summary="Liveness probe",
        description="Minimal probe — returns 200 if the process is alive.",
    )
    async def liveness() -> LivenessResponse:
        return LivenessResponse(status="alive")

    return router
