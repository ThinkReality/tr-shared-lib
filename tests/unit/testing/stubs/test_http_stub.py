from __future__ import annotations

import httpx
import pytest

from tr_shared.testing.stubs.http_stub import MockTransportBuilder


@pytest.mark.asyncio
async def test_static_json_route_matches_and_records_request() -> None:
    builder = MockTransportBuilder()
    builder.route("POST", r"/oauth/token$", json={"access_token": "t"})

    async with httpx.AsyncClient(
        transport=builder.build(), base_url="https://example.test"
    ) as client:
        resp = await client.post("/oauth/token", json={"grant_type": "client_credentials"})

    assert resp.status_code == 200
    assert resp.json() == {"access_token": "t"}
    assert len(builder.requests) == 1
    assert builder.requests[0].method == "POST"
    assert builder.requests[0].json == {"grant_type": "client_credentials"}


@pytest.mark.asyncio
async def test_callable_json_route_uses_path_match_groups() -> None:
    builder = MockTransportBuilder()
    builder.route("GET", r"/listings/(?P<id>[\w-]+)$", json=lambda m: {"id": m.group("id")})

    async with httpx.AsyncClient(
        transport=builder.build(), base_url="https://example.test"
    ) as client:
        resp = await client.get("/listings/abc-123")

    assert resp.json() == {"id": "abc-123"}


@pytest.mark.asyncio
async def test_unmatched_route_raises_with_a_useful_message() -> None:
    builder = MockTransportBuilder()
    builder.route("GET", r"/listings$", json={})

    async with httpx.AsyncClient(
        transport=builder.build(), base_url="https://example.test"
    ) as client:
        with pytest.raises(AssertionError, match="no route registered"):
            await client.get("/leads")
