import asyncio

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from tests.unit.middleware.asgi_harness import http_scope
from tr_shared.middleware import logging_middleware
from tr_shared.middleware.correlation_id import CorrelationIDMiddleware
from tr_shared.middleware.logging_middleware import DEFAULT_EXCLUDED_PATHS, LoggingMiddleware


def _build_app(excluded_paths=None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(LoggingMiddleware, service_name="test-svc", excluded_paths=excluded_paths)
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/api/test")
    def endpoint():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/client-error")
    def client_error():
        return Response(status_code=400)

    @app.get("/api/server-error")
    def server_error():
        return Response(status_code=500)

    @app.get("/api/explode")
    def explode():
        raise RuntimeError("kaboom")

    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _event(entries: list[dict], name: str) -> dict:
    return next(e for e in entries if e["event"] == name)


class TestDefaultExcludedPaths:
    @pytest.mark.parametrize("path", ["/health", "/docs", "/metrics", "/openapi.json"])
    def test_infrastructure_paths_are_excluded(self, path):
        assert path in DEFAULT_EXCLUDED_PATHS


class TestRequestCompleted:
    def test_carries_every_field_as_an_event_key(self, log_capture):
        entries = log_capture(logging_middleware)

        response = _client(_build_app()).get(
            "/api/test?page=2",
            headers={
                "X-Tenant-ID": "tenant-abc",
                "X-Forwarded-For": "10.0.0.1, 10.0.0.2",
                "User-Agent": "agent/1.0",
            },
        )

        completed = _event(entries, "request_completed")
        assert completed["method"] == "GET"
        assert completed["path"] == "/api/test"
        assert completed["status_code"] == 200
        assert isinstance(completed["duration_ms"], float) and completed["duration_ms"] >= 0
        assert completed["correlation_id"] == response.headers["x-correlation-id"]
        assert completed["tenant_id"] == "tenant-abc"
        assert completed["client_ip"] == "10.0.0.1"
        assert completed["user_agent"] == "agent/1.0"
        assert completed["query_string"] == "page=2"
        assert completed["service"] == "test-svc"

    def test_client_ip_falls_back_to_the_socket_peer(self, log_capture):
        entries = log_capture(logging_middleware)

        _client(_build_app()).get("/api/test")

        assert _event(entries, "request_completed")["client_ip"] == "testclient"

    def test_the_start_line_carries_the_correlation_id_too(self, log_capture):
        entries = log_capture(logging_middleware)

        response = _client(_build_app()).get("/api/test")

        started = _event(entries, "request_started")
        assert started["correlation_id"] == response.headers["x-correlation-id"]
        assert started["path"] == "/api/test"

    def test_no_stdlib_extra_dict_is_passed_through(self, log_capture):
        entries = log_capture(logging_middleware)

        _client(_build_app()).get("/api/test")

        assert all("extra" not in entry for entry in entries)


class TestLevels:
    @pytest.mark.parametrize(
        ("path", "level"),
        [("/api/test", "info"), ("/api/client-error", "warning"), ("/api/server-error", "warning")],
    )
    def test_completed_level_follows_the_status(self, log_capture, path, level):
        entries = log_capture(logging_middleware)

        _client(_build_app()).get(path)

        assert _event(entries, "request_completed")["log_level"] == level

    def test_an_unhandled_exception_is_logged_as_failed_and_re_raised(self, log_capture):
        entries = log_capture(logging_middleware)

        response = _client(_build_app()).get("/api/explode")

        failed = _event(entries, "request_failed")
        assert failed["error_type"] == "RuntimeError"
        assert failed["error_summary"] == "kaboom"
        assert failed["exc_info"]
        assert failed["duration_ms"] >= 0
        assert response.status_code == 500
        assert not any(e["event"] == "request_completed" for e in entries)


class TestExcludedPaths:
    def test_the_default_health_path_is_not_logged(self, log_capture):
        entries = log_capture(logging_middleware)

        _client(_build_app()).get("/health")

        assert entries == []

    def test_a_custom_excluded_path_is_not_logged(self, log_capture):
        entries = log_capture(logging_middleware)

        _client(_build_app(excluded_paths={"/api/test"})).get("/api/test")

        assert entries == []


class TestPassThrough:
    async def test_a_non_http_scope_is_handed_through_untouched(self, log_capture):
        entries = log_capture(logging_middleware)
        seen = {}

        async def app(scope, receive, send):
            seen["scope"] = scope

        scope = {"type": "lifespan"}
        await LoggingMiddleware(app, service_name="svc")(scope, lambda: None, lambda message: None)

        assert seen["scope"] is scope
        assert entries == []

    async def test_streamed_chunks_are_forwarded_as_they_are_produced(self, log_capture):
        log_capture(logging_middleware)
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

        from tests.unit.middleware.asgi_harness import receive

        await LoggingMiddleware(app, service_name="svc")(http_scope("/stream"), receive, send)

        assert [m.get("body") for m in forwarded[1:]] == [b"one", b"two"]
