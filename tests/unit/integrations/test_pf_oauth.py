"""Tests for fetch_pf_access_token()."""

import json

import httpx
import pytest

from tr_shared.integrations import (
    PF_AUTH_URL,
    IntegrationConfigError,
    fetch_pf_access_token,
)


def _make_client(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_happy_path_returns_token_and_expires_in() -> None:
    """The Atlas contract: credentials in a JSON body, camelCase response.

    Not OAuth2 client-credentials — there is no Basic auth header, no `scope`
    and no `grant_type`. Asserting the absence of the header matters: sending
    the secret twice would widen where it can leak.
    """
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth_header"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"accessToken": "tk-abc", "expiresIn": 3600})

    async with _make_client(httpx.MockTransport(handler)) as client:
        token, expires_in = await fetch_pf_access_token("my-key", "my-secret", http_client=client)

    assert token == "tk-abc"
    assert expires_in == 3600
    assert captured["url"] == PF_AUTH_URL
    assert captured["auth_header"] is None
    assert captured["content_type"] == "application/json"
    assert captured["body"] == {"apiKey": "my-key", "apiSecret": "my-secret"}


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
        return httpx.Response(200, json={"expiresIn": 3600})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("k", "s", http_client=client)
    assert "accessToken" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_expires_in_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accessToken": "tk"})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("k", "s", http_client=client)
    assert "expiresIn" in str(exc.value)


@pytest.mark.asyncio
async def test_snake_case_token_response_is_rejected() -> None:
    """A well-formed OAuth2 response is NOT a valid Atlas response.

    Without this, swapping the reader back to `access_token` would leave every
    other test in this file green — the happy path would simply stop being
    exercised by the shape the API actually returns.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tk", "expires_in": 3600})

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(IntegrationConfigError) as exc:
            await fetch_pf_access_token("k", "s", http_client=client)
    assert "accessToken" in str(exc.value)
