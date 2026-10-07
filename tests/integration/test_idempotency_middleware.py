"""APIIdempotencyMiddleware against a real Redis.

Every scenario shares one app and one middleware instance, because the middleware caches its
Redis client, and the client is bound to the event loop that first used it.
"""

import asyncio
import os
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import tr_shared.redis.client as redis_module
from tr_shared.contracts.headers import HttpHeader
from tr_shared.middleware.idempotency import APIIdempotencyMiddleware
from tr_shared.redis.client import close_redis_client

pytestmark = pytest.mark.integration

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")

if not TEST_REDIS_URL:
    pytest.skip("TEST_REDIS_URL not set — real-Redis integration skipped", allow_module_level=True)

MAX_RESPONSE_SIZE = 64
COMPLETED_TTL = 86400


class App:
    def __init__(self, service: str) -> None:
        self.calls: dict[str, int] = {}
        self.release = asyncio.Event()
        self.entered = asyncio.Event()
        routes = [
            Route("/status/{code:int}", self._status, methods=["POST"]),
            Route("/boom", self._boom, methods=["POST"]),
            Route("/big", self._big, methods=["POST"]),
            Route("/slow", self._slow, methods=["POST"]),
        ]
        self.asgi = Starlette(routes=routes)
        self.asgi.add_middleware(
            APIIdempotencyMiddleware,
            redis_url=TEST_REDIS_URL,
            service_name=service,
            max_response_size=MAX_RESPONSE_SIZE,
        )

    def _count(self, request: Request) -> int:
        self.calls[request.url.path] = self.calls.get(request.url.path, 0) + 1
        return self.calls[request.url.path]

    async def _status(self, request: Request) -> Response:
        call = self._count(request)
        return JSONResponse({"call": call}, status_code=request.path_params["code"])

    async def _boom(self, request: Request) -> Response:
        self._count(request)
        raise RuntimeError("untyped failure inside the route")

    async def _big(self, request: Request) -> Response:
        self._count(request)
        return JSONResponse({"blob": "x" * (MAX_RESPONSE_SIZE * 2)})

    async def _slow(self, request: Request) -> Response:
        call = self._count(request)
        self.entered.set()
        await self.release.wait()
        return JSONResponse({"call": call})


async def test_the_key_is_kept_only_for_answers_that_executed():
    assert TEST_REDIS_URL is not None
    redis_module._client = None
    service = f"itest-{uuid.uuid4().hex[:8]}"
    app = App(service)
    inspector = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    transport = httpx.ASGITransport(app=app.asgi, raise_app_exceptions=False)

    def stored(key: str) -> str:
        return f"{service}:idempotency:global:{key}"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def post(path: str, key: str) -> httpx.Response:
            return await client.post(path, headers={HttpHeader.IDEMPOTENCY_KEY.value: key})

        try:
            for code in (401, 403, 429):
                key = uuid.uuid4().hex
                first = await post(f"/status/{code}", key)
                second = await post(f"/status/{code}", key)
                assert (first.status_code, second.status_code) == (code, code)
                assert second.json() == {"call": 2}, f"{code} was replayed from the cache"
                assert await inspector.exists(stored(key)) == 0

            for code in (200, 400, 422):
                key = uuid.uuid4().hex
                first = await post(f"/status/{code}", key)
                second = await post(f"/status/{code}", key)
                assert second.json() == first.json()
                assert second.headers[HttpHeader.IDEMPOTENCY_REPLAYED.value] == "true"
                assert 0 < await inspector.ttl(stored(key)) <= COMPLETED_TTL
                assert await inspector.ttl(stored(key)) > COMPLETED_TTL - 60

            key = uuid.uuid4().hex
            assert (await post("/status/503", key)).status_code == 503
            assert await inspector.exists(stored(key)) == 0

            key = uuid.uuid4().hex
            assert (await post("/boom", key)).status_code == 500
            assert await inspector.exists(stored(key)) == 0
            assert (await post("/boom", key)).status_code == 500
            assert app.calls["/boom"] == 2, "an untyped error left the processing lock"

            key = uuid.uuid4().hex
            assert (await post("/big", key)).status_code == 200
            assert await inspector.exists(stored(key)) == 0
            assert (await post("/big", key)).status_code == 200
            assert app.calls["/big"] == 2, "an oversized answer left the processing lock"

            key = uuid.uuid4().hex
            in_flight = asyncio.create_task(post("/slow", key))
            await asyncio.wait_for(app.entered.wait(), timeout=5)
            assert 0 < await inspector.ttl(stored(key)) <= 300
            duplicate = await post("/slow", key)
            assert duplicate.status_code == 409
            assert duplicate.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
            in_flight.cancel()
            with pytest.raises(asyncio.CancelledError):
                await in_flight
            assert await inspector.exists(stored(key)) == 0, "a cancelled request kept its lock"
        finally:
            await inspector.aclose()
            await close_redis_client()
