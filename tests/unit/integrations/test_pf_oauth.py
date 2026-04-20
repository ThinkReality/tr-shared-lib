"""Tests for fetch_pf_access_token()."""

import base64

import httpx
import pytest

from tr_shared.integrations import IntegrationConfigError, fetch_pf_access_token


def _make_client(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_happy_path_returns_token_and_expires_in() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth_header"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type")
        captured["body"] = request.content
        return httpx.Response(200, json={"access_token": "tk-abc", "expires_in": 3600})

    async with _make_client(httpx.MockTransport(handler)) as client:
        token, expires_in = await fetch_pf_access_token(
            "my-key", "my-secret", http_client=client
        )

    assert token == "tk-abc"
    assert expires_in == 3600
    expected = base64.b64encode(b"my-key:my-secret").decode()
    assert captured["auth_header"] == f"Basic {expected}"
    assert captured["content_type"] == "application/json"
    assert b'"scope":"openid"' in captured["body"]
    assert b'"grant_type":"client_credentials"' in captured["body"]


@pytest.mark.asyncio
async def test_401_raises_integration_config_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("bad", "creds", http_client=client)
    assert "HTTP 401" in str(exc.value)


@pytest.mark.asyncio
async def test_429_raises_integration_config_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limited"})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError):
            await fetch_pf_access_token("k", "s", http_client=client)


@pytest.mark.asyncio
async def test_error_message_does_not_leak_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"secret_in_response": "my-key:my-secret"})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("my-key", "my-secret", http_client=client)
    assert "my-secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_network_error_raises_integration_config_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("k", "s", http_client=client)
    assert "ConnectError" in str(exc.value)


@pytest.mark.asyncio
async def test_non_json_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("k", "s", http_client=client)
    assert "not valid JSON" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_access_token_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"expires_in": 3600})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("k", "s", http_client=client)
    assert "access_token" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_expires_in_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tk"})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("k", "s", http_client=client)
    assert "expires_in" in str(exc.value)
