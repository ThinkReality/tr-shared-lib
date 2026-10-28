from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from tr_shared.health import create_health_router


async def get_ready(
    engine: Callable[[], AsyncEngine], redis: Callable[[], Awaitable[Redis | None]]
) -> httpx.Response:
    app = FastAPI()
    app.include_router(
        create_health_router("test-service", engine=engine, redis=redis),
        prefix="/api/v1/health",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/health/ready")
