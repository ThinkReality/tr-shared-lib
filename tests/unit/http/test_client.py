import httpx
import pytest
import structlog

from tr_shared.http.client import ServiceHTTPClient
from tr_shared.testing.stubs.http_stub import MockTransportBuilder

BASE_URL = "http://tr-crm-core:8000"


def _client(builder: MockTransportBuilder, **kwargs) -> ServiceHTTPClient:
    kwargs.setdefault("service_token", "test-token")
    return ServiceHTTPClient(
        service_name="crm-backend",
        base_url=BASE_URL,
        transport=builder.build(),
        **kwargs,
    )


class TestRequests:
    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def test_each_verb_reaches_the_transport_and_returns_its_json(self, method):
        builder = MockTransportBuilder().route(method, r"/things/1$", json={"id": 1})
        client = _client(builder)

        result = await getattr(client, method.lower())("/things/1")

        assert result == {"id": 1}
        assert [(r.method, r.url) for r in builder.requests] == [(method, f"{BASE_URL}/things/1")]

    async def test_the_json_body_is_sent(self):
        builder = MockTransportBuilder().route("POST", r"/things$", json={})
        client = _client(builder)

        await client.post("/things", json={"name": "x"})

        assert builder.requests[0].json == {"name": "x"}

    async def test_the_service_token_is_sent(self):
        builder = MockTransportBuilder().route("GET", r"/ping$", json={})

        await _client(builder).get("/ping")

        assert builder.requests[0].headers["x-service-token"] == "test-token"

    async def test_no_service_token_header_when_none_is_configured(self):
        builder = MockTransportBuilder().route("GET", r"/ping$", json={})

        await _client(builder, service_token="").get("/ping")

        assert "x-service-token" not in builder.requests[0].headers

    async def test_a_204_returns_an_empty_dict(self):
        builder = MockTransportBuilder().route("DELETE", r"/things/1$", status_code=204)

        assert await _client(builder).delete("/things/1") == {}

    async def test_a_non_json_body_is_returned_raw(self):
        builder = MockTransportBuilder().route(
            "GET",
            r"/text$",
            handler=lambda request, match: httpx.Response(200, text="plain"),
        )

        assert await _client(builder).get("/text") == {"raw": "plain"}


class TestFailures:
    async def test_a_4xx_raises_at_once_without_retrying_or_tripping_the_breaker(self):
        builder = MockTransportBuilder().route("GET", r"/missing$", status_code=404, json={})
        client = _client(builder, max_retries=3, failure_threshold=1)

        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/missing")

        assert len(builder.requests) == 1
        assert await client.circuit.is_open() is False

    async def test_a_5xx_counts_against_the_breaker_and_raises_connection_error(self):
        builder = MockTransportBuilder().route("GET", r"/boom$", status_code=503, json={})
        client = _client(builder, max_retries=1, failure_threshold=1)

        with pytest.raises(ConnectionError, match="failed after 1 retries"):
            await client.get("/boom")

        assert await client.circuit.is_open() is True

    async def test_an_open_breaker_rejects_without_sending(self):
        builder = MockTransportBuilder().route("GET", r"/boom$", status_code=503, json={})
        client = _client(builder, max_retries=1, failure_threshold=1)
        with pytest.raises(ConnectionError):
            await client.get("/boom")

        with pytest.raises(ConnectionError, match="Circuit breaker open"):
            await client.get("/boom")

        assert len(builder.requests) == 1


class TestLifecycle:
    async def test_the_client_is_reused_until_closed(self):
        builder = MockTransportBuilder().route("GET", r"/ping$", json={})
        client = _client(builder)

        await client.get("/ping")
        first = client._client
        await client.get("/ping")

        assert client._client is first

    async def test_a_closed_client_reopens_on_the_same_transport(self):
        builder = MockTransportBuilder().route("GET", r"/ping$", json={})

        async with _client(builder) as client:
            await client.get("/ping")
        await client.get("/ping")

        assert len(builder.requests) == 2

    async def test_closing_a_client_that_never_sent_is_a_noop(self):
        await _client(MockTransportBuilder()).close()


class TestCorrelationPropagation:
    @pytest.fixture(autouse=True)
    def _clean_context(self):
        structlog.contextvars.clear_contextvars()
        yield
        structlog.contextvars.clear_contextvars()

    async def _sent_headers(self, **request_kwargs) -> dict[str, str]:
        builder = MockTransportBuilder().route("GET", r"/ping$", json={})
        async with _client(builder) as client:
            await client.get("/ping", **request_kwargs)
        return builder.requests[0].headers

    async def test_the_bound_correlation_id_is_sent(self):
        structlog.contextvars.bind_contextvars(correlation_id="corr-1")

        headers = await self._sent_headers()

        assert headers["x-correlation-id"] == "corr-1"

    async def test_an_explicit_header_wins_over_the_bound_id(self):
        structlog.contextvars.bind_contextvars(correlation_id="corr-1")

        headers = await self._sent_headers(headers={"X-Correlation-ID": "explicit"})

        assert headers["x-correlation-id"] == "explicit"

    async def test_nothing_bound_sends_no_correlation_header(self):
        headers = await self._sent_headers()

        assert "x-correlation-id" not in headers
