import asyncio
import uuid

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tests.unit.middleware.asgi_harness import call, http_scope, receive, response_header
from tr_shared.logging import get_correlation_id
from tr_shared.middleware.correlation_id import CorrelationIDMiddleware


@pytest.fixture(autouse=True)
def _clean_context():
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def _recording_app(seen: dict):
    async def app(scope, receive, send):
        seen["during"] = get_correlation_id()
        seen["context"] = dict(structlog.contextvars.get_contextvars())
        seen["state"] = dict(scope.get("state", {}))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return app


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/test")
    def endpoint(request: Request):
        return {"correlation_id": getattr(request.state, "correlation_id", None)}

    @app.get("/bound-sync")
    def bound_in_a_threadpool_handler():
        return {"bound": get_correlation_id()}

    @app.get("/bound-async")
    async def bound_in_an_async_handler():
        return {"bound": get_correlation_id()}

    return app


class TestTheId:
    def test_generates_a_uuid4_when_absent(self):
        response = TestClient(_build_app()).get("/test")
        assert uuid.UUID(response.headers["x-correlation-id"]).version == 4

    def test_propagates_a_valid_incoming_id(self):
        response = TestClient(_build_app()).get("/test", headers={"X-Correlation-ID": "my-id-123"})
        assert response.headers["x-correlation-id"] == "my-id-123"
        assert response.json()["correlation_id"] == "my-id-123"

    @pytest.mark.parametrize(
        "incoming",
        ["gateway-20260930-" + str(uuid.uuid4()), "abc-123", "a" * 64],
        ids=["gateway-format", "short", "max-length"],
    )
    async def test_accepts_every_id_the_fleet_produces(self, incoming):
        messages = await call(
            CorrelationIDMiddleware(_recording_app({})),
            http_scope(headers=[("X-Correlation-ID", incoming)]),
        )
        assert response_header(messages, "X-Correlation-ID") == incoming

    @pytest.mark.parametrize(
        "incoming",
        ["has space", "a" * 65, "semi;colon", "colon:sep", "line\nbreak", "", "unicodé"],
        ids=["space", "too-long", "semicolon", "colon", "newline", "empty", "non-ascii"],
    )
    async def test_replaces_an_invalid_incoming_id_with_a_fresh_uuid4(self, incoming):
        seen: dict = {}
        messages = await call(
            CorrelationIDMiddleware(_recording_app(seen)),
            http_scope(headers=[("X-Correlation-ID", incoming)]),
        )
        issued = response_header(messages, "X-Correlation-ID")
        assert issued != incoming
        assert uuid.UUID(issued).version == 4
        assert seen["state"]["correlation_id"] == issued

    def test_different_requests_get_different_ids(self):
        client = TestClient(_build_app())
        assert (
            client.get("/test").headers["x-correlation-id"]
            != client.get("/test").headers["x-correlation-id"]
        )


class TestHandlersSeeTheBoundId:
    @pytest.mark.parametrize("path", ["/bound-sync", "/bound-async"])
    def test_sync_and_async_handlers_read_the_same_id_as_the_response(self, path):
        response = TestClient(_build_app()).get(path)

        assert response.json()["bound"] == response.headers["x-correlation-id"]


class TestRequestState:
    async def test_the_id_is_in_request_state_for_downstream_readers(self):
        seen: dict = {}
        messages = await call(CorrelationIDMiddleware(_recording_app(seen)), http_scope())
        assert seen["state"]["correlation_id"] == response_header(messages, "X-Correlation-ID")


class TestContextBinding:
    async def test_the_id_is_bound_during_the_call_and_gone_after(self):
        seen: dict = {}
        messages = await call(CorrelationIDMiddleware(_recording_app(seen)), http_scope())

        assert seen["during"] == response_header(messages, "X-Correlation-ID")
        assert get_correlation_id() is None

    async def test_an_earlier_binding_is_restored_not_wiped(self):
        structlog.contextvars.bind_contextvars(correlation_id="outer")

        await call(CorrelationIDMiddleware(_recording_app({})), http_scope())

        assert get_correlation_id() == "outer"

    async def test_service_name_survives_the_call(self):
        structlog.contextvars.bind_contextvars(service_name="svc")
        seen: dict = {}

        await call(CorrelationIDMiddleware(_recording_app(seen)), http_scope())

        assert seen["context"]["service_name"] == "svc"
        assert structlog.contextvars.get_contextvars()["service_name"] == "svc"

    async def test_the_id_is_unbound_when_the_app_raises(self):
        async def failing(scope, receive, send):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await call(CorrelationIDMiddleware(failing), http_scope())

        assert get_correlation_id() is None


class TestPassThrough:
    async def test_a_non_http_scope_is_handed_through_untouched(self):
        seen: dict = {}

        async def app(scope, receive, send):
            seen["scope"] = scope
            seen["bound"] = get_correlation_id()

        scope = {"type": "lifespan"}
        await CorrelationIDMiddleware(app)(scope, receive, lambda message: None)

        assert seen["scope"] is scope
        assert seen["bound"] is None
        assert "state" not in scope

    async def test_streamed_chunks_are_forwarded_as_they_are_produced(self):
        first_forwarded = asyncio.Event()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"one", "more_body": True})
            await asyncio.wait_for(first_forwarded.wait(), timeout=1)
            await send({"type": "http.response.body", "body": b"two", "more_body": False})

        forwarded: list[dict] = []

        async def send(message):
            forwarded.append(message)
            if message.get("body") == b"one":
                first_forwarded.set()

        await CorrelationIDMiddleware(app)(http_scope(), receive, send)

        assert [m.get("body") for m in forwarded[1:]] == [b"one", b"two"]
        assert response_header(forwarded, "X-Correlation-ID") is not None
