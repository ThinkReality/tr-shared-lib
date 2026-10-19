from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
from starlette.requests import Request

from tr_shared.rate_limiter.core import RateLimiter, default_identifier_extractor
from tr_shared.rate_limiter.dependency import create_rate_limit_dependency


def _caller(x_caller: str | None = Header(default=None)) -> str:
    if x_caller is None:
        raise HTTPException(status_code=401)
    return x_caller


def _caller_id(caller: str = Depends(_caller)) -> str:
    return f"user:{caller}"


def _app(limit: int = 1) -> FastAPI:
    app = FastAPI()
    check = create_rate_limit_dependency(
        RateLimiter(), identifier=_caller_id, limit=limit, window=60, key_prefix="test"
    )

    @app.get("/items/{item_id}", dependencies=[Depends(check)])
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    return app


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as c:
        yield c


async def _get(client: httpx.AsyncClient, caller: str | None, item: str = "1") -> httpx.Response:
    headers = {"X-Caller": caller} if caller else {}
    return await client.get(f"/items/{item}", headers=headers)


class TestTheBucketIsTheIdentifier:
    async def test_a_caller_over_the_limit_is_refused(self, client):
        assert (await _get(client, "alice")).status_code == 200

        assert (await _get(client, "alice")).status_code == 429

    async def test_another_caller_keeps_its_own_budget(self, client):
        await _get(client, "alice")
        await _get(client, "alice")

        assert (await _get(client, "bob")).status_code == 200

    async def test_ids_in_the_path_share_one_bucket(self, client):
        await _get(client, "alice", item=str(uuid4()))

        assert (await _get(client, "alice", item=str(uuid4()))).status_code == 429

    async def test_a_failing_identifier_answers_before_the_limiter_counts(self, client):
        assert (await _get(client, None)).status_code == 401
        assert (await _get(client, None)).status_code == 401

        assert (await _get(client, "alice")).status_code == 200


class TestTheRefusal:
    async def test_it_carries_the_rate_limit_headers(self, client):
        await _get(client, "alice")

        response = await _get(client, "alice")

        assert response.headers["X-RateLimit-Limit"] == "1"
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert int(response.headers["Retry-After"]) >= 1


def _request(headers: dict[str, str], host: str | None = "10.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (host, 1234) if host else None,
        }
    )


class TestDefaultIdentifierExtractor:
    def test_uses_the_first_forwarded_for_hop(self):
        assert (
            default_identifier_extractor(_request({"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}))
            == "203.0.113.5"
        )

    def test_uses_x_real_ip_without_forwarded_for(self):
        assert (
            default_identifier_extractor(_request({"X-Real-IP": "203.0.113.10"})) == "203.0.113.10"
        )

    def test_falls_back_to_the_socket_peer(self):
        assert default_identifier_extractor(_request({})) == "10.0.0.1"

    def test_unknown_without_a_client(self):
        assert default_identifier_extractor(_request({}, host=None)) == "unknown"

    def test_an_auth_context_on_state_does_not_change_the_key(self):
        request = _request({})
        request.state.auth_context = type("Ctx", (), {"user_id": "user-1"})()

        assert default_identifier_extractor(request) == "10.0.0.1"
