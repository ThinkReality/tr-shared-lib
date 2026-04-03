"""Tests for PrometheusClient."""
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx

from tr_shared.monitoring.prometheus_client import PrometheusClient


def _client():
    return PrometheusClient("http://prometheus:9090")


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _success(result):
    return {"status": "success", "data": {"result": result}}


class TestInitialization:
    def test_strips_trailing_slash(self):
        c = PrometheusClient("http://prom:9090/")
        assert c._base_url == "http://prom:9090"

    def test_creates_async_client(self):
        c = _client()
        assert isinstance(c._client, httpx.AsyncClient)


class TestClose:
    async def test_close_calls_aclose_when_open(self):
        c = _client()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        c._client = mock_http
        await c.close()
        mock_http.aclose.assert_awaited_once()

    async def test_close_skips_aclose_when_already_closed(self):
        c = _client()
        mock_http = AsyncMock()
        mock_http.is_closed = True
        c._client = mock_http
        await c.close()
        mock_http.aclose.assert_not_awaited()


class TestQuery:
    async def test_returns_result_vector_on_success(self):
        c = _client()
        payload = _success([{"metric": {}, "value": [1234, "5.0"]}])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        result = await c._query("some_metric")
        assert len(result) == 1

    async def test_returns_empty_on_error_status(self):
        c = _client()
        payload = {"status": "error", "error": "bad query"}
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        result = await c._query("bad_metric")
        assert result == []

    async def test_returns_empty_on_http_error(self):
        c = _client()
        c._client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))

        result = await c._query("any_metric")
        assert result == []

    async def test_calls_correct_endpoint(self):
        c = _client()
        payload = _success([])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        await c._query("my_query")
        c._client.get.assert_awaited_once()
        path = c._client.get.call_args[0][0]
        assert "/api/v1/query" in path


class TestQueryScalar:
    async def test_returns_float_value(self):
        c = _client()
        payload = _success([{"metric": {}, "value": [1234, "3.14"]}])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        val = await c._query_scalar("q")
        assert val == pytest.approx(3.14)

    async def test_returns_default_when_empty(self):
        c = _client()
        payload = _success([])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        val = await c._query_scalar("q", default=42.0)
        assert val == 42.0

    async def test_returns_default_for_nan(self):
        c = _client()
        payload = _success([{"value": [1234, "NaN"]}])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        val = await c._query_scalar("q", default=0.0)
        assert val == 0.0

    async def test_returns_default_for_inf(self):
        c = _client()
        payload = _success([{"value": [1234, "Inf"]}])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        val = await c._query_scalar("q", default=0.0)
        assert val == 0.0


class TestGetRequestRate:
    async def test_returns_float(self):
        c = _client()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            c, "_query_scalar", new=AsyncMock(return_value=5.0)
        ):
            rate = await c.get_request_rate("my-service")
            assert rate == 5.0


class TestGetErrorRate:
    async def test_returns_float(self):
        c = _client()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            c, "_query_scalar", new=AsyncMock(return_value=2.5)
        ):
            rate = await c.get_error_rate("my-service")
            assert rate == 2.5


class TestIsServiceUp:
    async def test_returns_true_when_value_is_one(self):
        c = _client()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            c, "_query_scalar", new=AsyncMock(return_value=1.0)
        ):
            assert await c.is_service_up("svc") is True

    async def test_returns_false_when_value_is_zero(self):
        c = _client()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            c, "_query_scalar", new=AsyncMock(return_value=0.0)
        ):
            assert await c.is_service_up("svc") is False


class TestGetServiceOverview:
    async def test_returns_all_expected_keys(self):
        c = _client()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            c, "_query_scalar", new=AsyncMock(return_value=1.0)
        ):
            overview = await c.get_service_overview("svc")
            assert overview["service"] == "svc"
            assert "request_rate" in overview
            assert "error_rate" in overview
            assert "p95_latency_s" in overview
            assert "p99_latency_s" in overview
            assert "active_requests" in overview
            assert "is_up" in overview


class TestGetAllServicesStatus:
    async def test_returns_service_list(self):
        c = _client()
        payload = _success([
            {"metric": {"job": "crm-backend"}, "value": [1234, "1"]},
            {"metric": {"job": "tr-listing"}, "value": [1234, "0"]},
        ])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        result = await c.get_all_services_status()
        assert len(result) == 2
        services = {s["service"]: s["is_up"] for s in result}
        assert services["crm-backend"] is True
        assert services["tr-listing"] is False


class TestGetTopEndpoints:
    async def test_returns_endpoint_list(self):
        c = _client()
        payload = _success([
            {
                "metric": {"http_route": "/api/v1/test", "http_method": "GET"},
                "value": [1234, "10.0"],
            },
        ])
        c._client.get = AsyncMock(return_value=_mock_response(payload))

        result = await c.get_top_endpoints("svc", limit=5)
        assert len(result) == 1
        assert result[0]["endpoint"] == "/api/v1/test"
        assert result[0]["request_rate"] == pytest.approx(10.0)
