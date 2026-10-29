import asyncio
import logging
import time

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from tests.unit.health.readiness_harness import get_ready
from tr_shared.health import router

REFUSING_DSN = "postgresql+asyncpg://app:secret@127.0.0.1:1/app"
REFUSING_REDIS = "redis://127.0.0.1:1/0"


def failures(caplog: pytest.LogCaptureFixture) -> set[tuple[str, str]]:
    return {
        (record.check, record.error_type)
        for record in caplog.records
        if record.getMessage() == "health_check_failed"
    }


async def test_unreachable_dependencies_answer_503_and_keep_the_reason_server_side(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine(REFUSING_DSN)
    redis = Redis.from_url(REFUSING_REDIS)

    async def get_redis() -> Redis:
        return redis

    with caplog.at_level(logging.WARNING, logger=router.__name__):
        response = await get_ready(lambda: engine, get_redis)
    await engine.dispose()
    await redis.aclose()

    body = response.json()
    assert response.status_code == 503
    assert (body["status"], body["checks"]) == ("not_ready", {"database": False, "redis": False})
    assert [set(detail) for detail in body["details"]] == [{"name", "healthy", "latency_ms"}] * 2
    assert "127.0.0.1" not in response.text
    assert failures(caplog) == {
        ("database", "ConnectionRefusedError"),
        ("redis", "ConnectionError"),
    }


async def test_a_missing_redis_client_is_not_ready(caplog: pytest.LogCaptureFixture) -> None:
    engine = create_async_engine(REFUSING_DSN)

    async def no_client() -> None:
        return None

    with caplog.at_level(logging.WARNING, logger=router.__name__):
        response = await get_ready(lambda: engine, no_client)
    await engine.dispose()

    assert response.status_code == 503
    assert response.json()["checks"]["redis"] is False
    assert ("redis", "ConnectionError") in failures(caplog)


async def test_hanging_dependencies_answer_within_one_probe_budget(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(router, "PROBE_TIMEOUT_SECONDS", 0.2)
    silent_peers: list[asyncio.StreamWriter] = []
    server = await asyncio.start_server(
        lambda _reader, writer: silent_peers.append(writer), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    engine = create_async_engine(f"postgresql+asyncpg://app:secret@127.0.0.1:{port}/app")

    async def hang() -> None:
        await asyncio.Event().wait()

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger=router.__name__):
        async with asyncio.timeout(5):
            response = await get_ready(lambda: engine, hang)
    elapsed = time.monotonic() - started
    await engine.dispose()
    for writer in silent_peers:
        writer.close()
    server.close()

    assert response.status_code == 503
    assert elapsed < 0.4
    assert failures(caplog) == {("database", "TimeoutError"), ("redis", "TimeoutError")}
