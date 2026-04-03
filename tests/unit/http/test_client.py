"""Tests for ServiceHTTPClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tr_shared.http.client import ServiceHTTPClient
from tr_shared.http.circuit_breaker import CircuitBreaker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(**kwargs) -> ServiceHTTPClient:
    return ServiceHTTPClient(
        service_name="crm-backend",
        base_url="http://crm-backend:8000",
        service_token="test-token",
        **kwargs,
    )


def _mock_response(json_data=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {"ok": True}
    response.raise_for_status = MagicMock()
    return response


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_service_name_stored(self):
        c = _client()
        assert c.service_name == "crm-backend"

    def test_base_url_stored(self):
        c = _client()
        assert c.base_url == "http://crm-backend:8000"

    def test_service_token_stored(self):
        c = _client()
        assert c.service_token == "test-token"

    def test_circuit_breaker_created(self):
        c = _client()
        assert isinstance(c.circuit, CircuitBreaker)

    def test_default_client_is_none(self):
        c = _client()
        assert c._client is None


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------

class TestGetClient:
    async def test_creates_httpx_client(self):
        c = _client()
        with patch("tr_shared.http.client.httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value = MagicMock(is_closed=False)
            http = await c._get_client()
            mock_httpx.assert_called_once()

    async def test_includes_service_token_header(self):
        c = _client()
        created_headers = {}
        def fake_client(**kwargs):
            created_headers.update(kwargs.get("headers", {}))
            m = MagicMock()
            m.is_closed = False
            return m
        with patch("tr_shared.http.client.httpx.AsyncClient", side_effect=fake_client):
            await c._get_client()
        assert created_headers.get("X-Service-Token") == "test-token"

    async def test_no_service_token_header_when_empty(self):
        c = ServiceHTTPClient(
            service_name="svc", base_url="http://svc:8000", service_token=""
        )
        created_headers = {}
        def fake_client(**kwargs):
            created_headers.update(kwargs.get("headers", {}))
            m = MagicMock()
            m.is_closed = False
            return m
        with patch("tr_shared.http.client.httpx.AsyncClient", side_effect=fake_client):
            await c._get_client()
        assert "X-Service-Token" not in created_headers

    async def test_returns_same_client_if_open(self):
        c = _client()
        mock_http = MagicMock()
        mock_http.is_closed = False
        c._client = mock_http
        with patch("tr_shared.http.client.httpx.AsyncClient") as mock_cls:
            result = await c._get_client()
            assert result is mock_http
            mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestClose:
    async def test_close_calls_aclose(self):
        c = _client()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        c._client = mock_http
        await c.close()
        mock_http.aclose.assert_awaited_once()

    async def test_close_sets_client_to_none(self):
        c = _client()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        c._client = mock_http
        await c.close()
        assert c._client is None

    async def test_close_when_no_client_is_noop(self):
        c = _client()
        await c.close()  # Should not raise


# ---------------------------------------------------------------------------
# _request — circuit breaker open
# ---------------------------------------------------------------------------

class TestRequestCircuitBreaker:
    async def test_raises_connection_error_when_circuit_open(self):
        c = _client()
        c.circuit.state = MagicMock()
        with patch.object(c.circuit, "is_open", new=AsyncMock(return_value=True)):
            with pytest.raises(ConnectionError, match="Circuit breaker open"):
                await c._request("GET", "/test")


# ---------------------------------------------------------------------------
# HTTP verb convenience methods
# ---------------------------------------------------------------------------

class TestHttpVerbs:
    async def test_get_calls_request_with_get(self):
        c = _client()
        with patch.object(c, "_request", new=AsyncMock(return_value={"ok": True})) as mock:
            await c.get("/test")
            mock.assert_awaited_once()
            assert mock.call_args[0][0] == "GET"

    async def test_post_calls_request_with_post(self):
        c = _client()
        with patch.object(c, "_request", new=AsyncMock(return_value={})) as mock:
            await c.post("/test", json={"k": "v"})
            assert mock.call_args[0][0] == "POST"

    async def test_put_calls_request_with_put(self):
        c = _client()
        with patch.object(c, "_request", new=AsyncMock(return_value={})) as mock:
            await c.put("/test", json={"k": "v"})
            assert mock.call_args[0][0] == "PUT"

    async def test_patch_calls_request_with_patch(self):
        c = _client()
        with patch.object(c, "_request", new=AsyncMock(return_value={})) as mock:
            await c.patch("/test", json={"k": "v"})
            assert mock.call_args[0][0] == "PATCH"

    async def test_delete_calls_request_with_delete(self):
        c = _client()
        with patch.object(c, "_request", new=AsyncMock(return_value={})) as mock:
            await c.delete("/test")
            assert mock.call_args[0][0] == "DELETE"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    async def test_aenter_returns_self(self):
        c = _client()
        with patch.object(c, "_get_client", new=AsyncMock(return_value=MagicMock())):
            result = await c.__aenter__()
            assert result is c

    async def test_aexit_calls_close(self):
        c = _client()
        with patch.object(c, "close", new=AsyncMock()) as mock_close:
            await c.__aexit__(None, None, None)
            mock_close.assert_awaited_once()
