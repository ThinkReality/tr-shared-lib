import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from tests.unit.health.readiness_harness import get_ready

pytestmark = pytest.mark.integration


async def test_reachable_dependencies_answer_ready(postgres_dsn: str, redis_url: str) -> None:
    engine = create_async_engine(postgres_dsn)
    redis = Redis.from_url(redis_url)

    async def get_redis() -> Redis:
        return redis

    response = await get_ready(lambda: engine, get_redis)
    await engine.dispose()
    await redis.aclose()

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["checks"]) == ("ready", {"database": True, "redis": True})
