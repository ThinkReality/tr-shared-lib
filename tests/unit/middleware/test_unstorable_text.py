import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.applications import Starlette

from tr_shared.middleware import UnstorableTextMiddleware
from tr_shared.schemas.error_envelope import set_error_code_prefix

_APP = Starlette()
set_error_code_prefix(_APP, "TEST")

JSON = "application/json"


def _scope(
    *,
    method: str = "POST",
    path: str = "/items",
    query: bytes = b"",
    content_type: str | None = JSON,
    scope_type: str = "http",
) -> dict:
    headers = [] if content_type is None else [(b"content-type", content_type.encode())]
    return {
        "type": scope_type,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": headers,
        "state": {"correlation_id": "cid-1"},
        "app": _APP,
    }


async def _run(scope: dict, *chunks: bytes) -> tuple[int, dict | None, list[bytes] | None]:
    pending = list(chunks) or [b""]
    received: list[bytes] | None = None

    async def receive() -> dict:
        if pending:
            body = pending.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    async def downstream(scope, receive, send):
        nonlocal received
        received = []
        while True:
            message = await receive()
            received.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"reached"})

    messages: list[dict] = []

    async def send(message: dict) -> None:
        messages.append(message)

    await UnstorableTextMiddleware(downstream)(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    payload = None if start["status"] == 200 else json.loads(body)
    return start["status"], payload, received


def _rejected_loc(payload: dict) -> list:
    error = payload["error"]
    assert error["code"] == "TEST_VALIDATION_000"
    assert error["correlation_id"] == "cid-1"
    [field] = error["fields"]
    assert field["type"] == "string_unstorable"
    return field["loc"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b'{"description": "night\\u0000shift"}', id="escaped-nul"),
        pytest.param(b'{"description": "a\\ud800b"}', id="escaped-lone-surrogate"),
        pytest.param(b'{"description": "a\xed\xa0\x80b"}', id="raw-surrogate-bytes"),
    ],
)
async def test_a_json_body_with_unstorable_text_is_a_422(body):
    status, payload, received = await _run(_scope(), body)

    assert status == 422
    assert _rejected_loc(payload) == ["body", "description"]
    assert received is None


@pytest.mark.parametrize(
    "content_type",
    [
        pytest.param("application/json; charset=utf-8", id="charset"),
        pytest.param("application/vnd.api+json", id="plus-json"),
        pytest.param(None, id="missing"),
    ],
)
async def test_every_content_type_fastapi_parses_as_json_is_checked(content_type):
    status, payload, _ = await _run(_scope(content_type=content_type), b'{"n": "\\u0000"}')

    assert status == 422
    assert _rejected_loc(payload) == ["body", "n"]


async def test_a_nested_value_reports_its_full_location():
    status, payload, _ = await _run(_scope(), b'{"meta": {"tags": ["ok", "\\u0000"]}}')

    assert status == 422
    assert _rejected_loc(payload) == ["body", "meta", "tags", 1]


async def test_an_unstorable_key_is_reported_without_echoing_it():
    status, payload, _ = await _run(_scope(), b'{"meta": {"k\\ud800": 1}}')

    assert status == 422
    assert _rejected_loc(payload) == ["body", "meta"]


async def test_an_urlencoded_form_field_is_checked():
    scope = _scope(content_type="application/x-www-form-urlencoded")

    status, payload, _ = await _run(scope, b"name=a%00b&other=ok")

    assert status == 422
    assert _rejected_loc(payload) == ["body", "name"]


async def test_a_query_parameter_is_checked():
    status, payload, _ = await _run(_scope(method="GET", query=b"search=a%00b"), b"")

    assert status == 422
    assert _rejected_loc(payload) == ["query", "search"]


async def test_the_path_is_checked():
    status, payload, _ = await _run(_scope(method="GET", path="/items/a\x00b"), b"")

    assert status == 422
    assert _rejected_loc(payload) == ["path"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b'{"d": "\\\\u0000"}', id="escaped-backslash"),
        pytest.param(b'{"d": "\\ud83d\\ude00"}', id="escaped-emoji-pair"),
        pytest.param(b'{"d": "plain", "n": 1, "x": null}', id="plain"),
        pytest.param(b'{"d": "\\u0000"', id="invalid-json-left-to-fastapi"),
    ],
)
async def test_storable_or_unparseable_json_reaches_the_app(body):
    status, _, received = await _run(_scope(), body)

    assert status == 200
    assert b"".join(received) == body


async def test_multipart_is_not_inspected():
    body = b'--b\r\nContent-Disposition: form-data; name="f"; filename="x"\r\n\r\n\x00\x01\r\n--b--'

    status, _, received = await _run(_scope(content_type="multipart/form-data; boundary=b"), body)

    assert status == 200
    assert b"".join(received) == body


async def test_a_body_sent_in_chunks_is_checked_whole_and_replayed_whole():
    status, _, received = await _run(_scope(), b'{"d": "pla', b'in", "e": "', b'ok"}')

    assert status == 200
    assert b"".join(received) == b'{"d": "plain", "e": "ok"}'


async def test_unstorable_text_split_across_chunks_is_still_found():
    status, _, _ = await _run(_scope(), b'{"d": "a\\u00', b'00b"}')

    assert status == 422


async def test_non_http_scopes_pass_through_untouched():
    seen = []

    async def downstream(scope, receive, send):
        seen.append(scope["type"])

    await UnstorableTextMiddleware(downstream)({"type": "lifespan"}, None, None)

    assert seen == ["lifespan"]


class _Role(BaseModel):
    description: str


def _fastapi_app() -> FastAPI:
    app = FastAPI()
    set_error_code_prefix(app, "TEST")
    app.add_middleware(UnstorableTextMiddleware)

    @app.post("/roles")
    def create(role: _Role) -> dict:
        return {"description": role.description}

    return app


async def _post_roles(**kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=_fastapi_app())
    async with asyncio.timeout(5), httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.post("/roles", **kwargs)


async def test_a_real_fastapi_route_still_parses_the_replayed_body():
    response = await _post_roles(json={"description": "night \U0001f319"})

    assert response.status_code == 200
    assert response.json() == {"description": "night \U0001f319"}


async def test_a_real_fastapi_route_never_sees_unstorable_text():
    response = await _post_roles(
        content=b'{"description": "a\\ud800b"}', headers={"content-type": JSON}
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["loc"] == ["body", "description"]


async def test_json_too_deep_for_the_parser_is_left_to_the_app():
    body = b"[" * 200_000 + b"]" * 200_000

    status, _, received = await _run(_scope(), body)

    assert status == 200
    assert b"".join(received) == body
