import asyncio
import os
import uuid

import httpx
import pytest
import redis
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from tr_shared.cache.adapters.standard_redis import StandardRedisAdapter
from tr_shared.contracts.headers import HttpHeader
from tr_shared.contracts.taxonomy import Feature
from tr_shared.events.producer import EventProducer
from tr_shared.middleware.idempotency import APIIdempotencyMiddleware
from tr_shared.redis import close_redis_client, get_redis_client
from tr_shared.webhooks.idempotency import WebhookIdempotencyGuard

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)


@pytest.fixture
def inspector():
    assert TEST_REDIS_URL is not None
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    yield client
    client.close()


def test_a_cache_adapter_serves_every_event_loop():
    assert TEST_REDIS_URL is not None
    adapter = StandardRedisAdapter(url=TEST_REDIS_URL)
    key = f"itest:{uuid.uuid4().hex}"
    assert asyncio.run(adapter.initialize())

    try:
        asyncio.run(adapter.set(key, "v", ttl=60))
        assert asyncio.run(adapter.get(key)) == "v"
    finally:
        asyncio.run(adapter.close())


def test_the_shared_client_serves_every_event_loop():
    assert TEST_REDIS_URL is not None
    key = f"itest:{uuid.uuid4().hex}"

    async def write() -> None:
        await (await get_redis_client(TEST_REDIS_URL)).set(key, "v", ex=60)

    async def read() -> str | None:
        return await (await get_redis_client(TEST_REDIS_URL)).get(key)

    try:
        asyncio.run(write())
        assert asyncio.run(read()) == "v"
    finally:
        asyncio.run(close_redis_client())


def test_an_event_producer_publishes_from_every_event_loop(inspector):
    stream = f"itest:{uuid.uuid4().hex}"
    producer = EventProducer(
        redis_url=TEST_REDIS_URL, stream_name=stream, source_service=Feature.TASK
    )

    try:
        asyncio.run(producer.publish("task.created", "t1", {}))
        asyncio.run(producer.publish("task.updated", "t1", {}))
    finally:
        asyncio.run(producer.disconnect())
        published = [fields["event_type"] for _id, fields in inspector.xrange(stream)]
        inspector.delete(stream)

    assert published == ["task.created", "task.updated"]


def test_the_idempotency_middleware_replays_an_answer_in_a_later_event_loop():
    async def ok(request: Request) -> JSONResponse:
        return JSONResponse({})

    app = Starlette(routes=[Route("/", ok, methods=["POST"])])
    app.add_middleware(
        APIIdempotencyMiddleware,
        redis_url=TEST_REDIS_URL,
        service_name=f"itest-{uuid.uuid4().hex[:8]}",
    )

    async def post(*keys: str) -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [
                await client.post("/", headers={HttpHeader.IDEMPOTENCY_KEY.value: key})
                for key in keys
            ]

    key = uuid.uuid4().hex
    try:
        asyncio.run(post(uuid.uuid4().hex))
        _first, retry = asyncio.run(post(key, key))
    finally:
        asyncio.run(close_redis_client())

    assert retry.status_code == 200
    assert retry.headers[HttpHeader.IDEMPOTENCY_REPLAYED.value] == "true"


def test_the_webhook_guard_recognises_a_duplicate_from_another_event_loop():
    guard = WebhookIdempotencyGuard(
        redis_url=TEST_REDIS_URL, key_prefix=f"itest-{uuid.uuid4().hex[:8]}"
    )
    event_id = uuid.uuid4().hex

    try:
        first = asyncio.run(guard.is_duplicate("pf", event_id))
        second = asyncio.run(guard.is_duplicate("pf", event_id))
    finally:
        asyncio.run(close_redis_client())

    assert (first, second) == (False, True)
