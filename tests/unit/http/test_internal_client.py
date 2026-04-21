"""Tests for tr_shared.http.InternalServiceClient."""

from unittest.mock import AsyncMock

import httpx
import pytest

from tr_shared.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)
from tr_shared.http import InternalServiceClient, ServiceHTTPClient


def _make_http() -> ServiceHTTPClient:
    """Return a real ServiceHTTPClient with AsyncMock HTTP methods."""
    http = ServiceHTTPClient(service_name="test", base_url="http://svc")
    http.get = AsyncMock()
    http.post = AsyncMock()
    http.patch = AsyncMock()
    http.delete = AsyncMock()
    return http


def _status_error(status: int, body: dict | None = None) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://svc/x")
    content = body if body is not None else {"error": "err", "detail": "d", "code": "C_001"}
    resp = httpx.Response(status, request=req, json=content)
    return httpx.HTTPStatusError("err", request=req, response=resp)


class _Client(InternalServiceClient):
    BASE_PATH = "/api/v1/internal"


class TestEnvelopeParsing:
    async def test_extracts_data_on_success(self):
        http = _make_http()
        http.get.return_value = {
            "status": "success",
            "message": "ok",
            "data": {"count": 3},
        }
        client = _Client(http)
        result = await client._get("/foo")
        assert result == {"count": 3}

    async def test_delete_204_returns_none(self):
        http = _make_http()
        http.delete.return_value = {}
        client = _Client(http)
        assert await client._delete("/foo") is None

    async def test_missing_data_raises_service_unavailable(self):
        http = _make_http()
        http.get.return_value = {"status": "success"}
        client = _Client(http)
        with pytest.raises(ServiceUnavailableError) as ei:
            await client._get("/foo")
        assert "missing 'data'" in ei.value.detail_message

    async def test_non_dict_envelope_raises(self):
        http = _make_http()
        http.get.return_value = "not-a-dict"
        client = _Client(http)
        with pytest.raises(ServiceUnavailableError) as ei:
            await client._get("/foo")
        assert "not a JSON object" in ei.value.detail_message


class TestTenantHeader:
    async def test_tenant_id_injected_as_header(self):
        http = _make_http()
        http.get.return_value = {"data": {}}
        client = _Client(http)
        await client._get("/foo", tenant_id="tenant-uuid-1")
        call_kwargs = http.get.call_args.kwargs
        assert call_kwargs["headers"]["X-Tenant-ID"] == "tenant-uuid-1"

    async def test_no_tenant_no_header(self):
        http = _make_http()
        http.get.return_value = {"data": {}}
        client = _Client(http)
        await client._get("/foo")
        call_kwargs = http.get.call_args.kwargs
        assert "X-Tenant-ID" not in call_kwargs["headers"]


class TestErrorTranslation:
    @pytest.mark.parametrize(
        ("status", "expected_exc"),
        [
            (400, ValidationError),
            (401, AuthenticationError),
            (403, AuthorizationError),
            (404, NotFoundError),
            (409, ConflictError),
            (429, RateLimitError),
            (500, ServiceUnavailableError),
            (502, ServiceUnavailableError),
            (503, ServiceUnavailableError),
        ],
    )
    async def test_status_maps_to_exception(self, status, expected_exc):
        http = _make_http()
        http.get.side_effect = _status_error(status)
        client = _Client(http)
        with pytest.raises(expected_exc):
            await client._get("/foo")

    async def test_timeout_maps_to_service_timeout(self):
        http = _make_http()
        http.get.side_effect = httpx.TimeoutException("slow")
        client = _Client(http)
        with pytest.raises(ServiceTimeoutError):
            await client._get("/foo")

    async def test_connection_error_maps_to_unavailable(self):
        http = _make_http()
        http.get.side_effect = ConnectionError("breaker open")
        client = _Client(http)
        with pytest.raises(ServiceUnavailableError) as ei:
            await client._get("/foo")
        assert "breaker open" in ei.value.detail_message

    async def test_httpx_request_error_maps_to_unavailable(self):
        http = _make_http()
        http.get.side_effect = httpx.RequestError(
            "network", request=httpx.Request("GET", "http://svc"),
        )
        client = _Client(http)
        with pytest.raises(ServiceUnavailableError):
            await client._get("/foo")

    async def test_error_detail_propagates(self):
        http = _make_http()
        http.get.side_effect = _status_error(
            400, body={"error": "Validation failed", "detail": "bad x", "code": "V_001"},
        )
        client = _Client(http)
        with pytest.raises(ValidationError) as ei:
            await client._get("/foo")
        assert "bad x" in ei.value.detail_message
        assert ei.value.error_code == "V_001"


class TestBasePath:
    async def test_base_path_prefixed(self):
        http = _make_http()
        http.get.return_value = {"data": {}}
        client = _Client(http)
        await client._get("/leads/stats")
        assert http.get.call_args.args[0] == "/api/v1/internal/leads/stats"

    async def test_no_base_path_passes_through(self):
        class Bare(InternalServiceClient):
            pass

        http = _make_http()
        http.get.return_value = {"data": {}}
        client = Bare(http)
        await client._get("/whatever")
        assert http.get.call_args.args[0] == "/whatever"


class TestVerbs:
    async def test_post(self):
        http = _make_http()
        http.post.return_value = {"data": {"ok": True}}
        client = _Client(http)
        await client._post("/x", json={"a": 1})
        http.post.assert_awaited_once()

    async def test_patch(self):
        http = _make_http()
        http.patch.return_value = {"data": {"ok": True}}
        client = _Client(http)
        await client._patch("/x", json={"a": 1})
        http.patch.assert_awaited_once()

    async def test_unsupported_method_raises(self):
        http = _make_http()
        client = _Client(http)
        with pytest.raises(ValueError, match="Unsupported method"):
            await client._call("OPTIONS", "/x")
