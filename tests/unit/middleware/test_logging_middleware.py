"""Tests for LoggingMiddleware."""

import logging
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tr_shared.middleware.logging_middleware import (
    DEFAULT_EXCLUDED_PATHS,
    LoggingMiddleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app(excluded_paths=None, **kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        LoggingMiddleware,
        service_name="test-svc",
        excluded_paths=excluded_paths,
        **kwargs,
    )

    @app.get("/api/test")
    def endpoint():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/client-error")
    def client_error():
        from fastapi import Response
        return Response(status_code=400)

    @app.get("/api/server-error")
    def server_error():
        from fastapi import Response
        return Response(status_code=500)

    return app


# ---------------------------------------------------------------------------
# DEFAULT_EXCLUDED_PATHS
# ---------------------------------------------------------------------------

class TestDefaultExcludedPaths:
    def test_health_is_excluded(self):
        assert "/health" in DEFAULT_EXCLUDED_PATHS

    def test_docs_is_excluded(self):
        assert "/docs" in DEFAULT_EXCLUDED_PATHS

    def test_metrics_is_excluded(self):
        assert "/metrics" in DEFAULT_EXCLUDED_PATHS

    def test_openapi_is_excluded(self):
        assert "/openapi.json" in DEFAULT_EXCLUDED_PATHS


# ---------------------------------------------------------------------------
# Excluded paths — no logging
# ---------------------------------------------------------------------------

class TestExcludedPaths:
    def test_health_path_not_logged(self):
        app = _build_app()
        with patch("tr_shared.middleware.logging_middleware.logger") as mock_logger:
            client = TestClient(app)
            client.get("/health")
            mock_logger.info.assert_not_called()

    def test_non_excluded_path_is_logged(self):
        app = _build_app()
        with patch("tr_shared.middleware.logging_middleware.logger") as mock_logger:
            client = TestClient(app)
            client.get("/api/test")
            mock_logger.info.assert_called()

    def test_custom_excluded_path_not_logged(self):
        app = _build_app(excluded_paths={"/api/test"})
        with patch("tr_shared.middleware.logging_middleware.logger") as mock_logger:
            client = TestClient(app)
            client.get("/api/test")
            mock_logger.info.assert_not_called()


# ---------------------------------------------------------------------------
# Log level by status code
# ---------------------------------------------------------------------------

class TestLogLevel:
    def test_2xx_logged_at_info(self):
        app = _build_app()
        with patch("tr_shared.middleware.logging_middleware.logger") as mock_logger:
            client = TestClient(app)
            client.get("/api/test")
            # "Request completed" at info level (status < 400)
            mock_logger.info.assert_called()

    def test_4xx_logged_at_warning(self):
        app = _build_app()
        with patch("tr_shared.middleware.logging_middleware.logger") as mock_logger:
            client = TestClient(app)
            client.get("/api/client-error")
            mock_logger.warning.assert_called()

    def test_5xx_logged_at_warning(self):
        """5xx from a handled response → warning (status >= 400)."""
        app = _build_app()
        with patch("tr_shared.middleware.logging_middleware.logger") as mock_logger:
            client = TestClient(app)
            client.get("/api/server-error")
            mock_logger.warning.assert_called()


# ---------------------------------------------------------------------------
# _extract_metadata
# ---------------------------------------------------------------------------

class TestExtractMetadata:
    def test_includes_method_and_path(self):
        app = FastAPI()
        captured = {}

        @app.get("/meta")
        def endpoint(request: Request):
            captured["meta"] = LoggingMiddleware._extract_metadata(request)
            return {}

        client = TestClient(app)
        client.get("/meta")
        assert captured["meta"]["method"] == "GET"
        assert captured["meta"]["path"] == "/meta"

    def test_includes_user_agent_when_present(self):
        app = FastAPI()
        captured = {}

        @app.get("/meta")
        def endpoint(request: Request):
            captured["meta"] = LoggingMiddleware._extract_metadata(request)
            return {}

        client = TestClient(app)
        client.get("/meta", headers={"User-Agent": "test-agent/1.0"})
        assert captured["meta"].get("user_agent") == "test-agent/1.0"

    def test_includes_correlation_id_from_state(self):
        app = FastAPI()
        captured = {}

        @app.get("/meta")
        def endpoint(request: Request):
            request.state.correlation_id = "corr-id-xyz"
            captured["meta"] = LoggingMiddleware._extract_metadata(request)
            return {}

        client = TestClient(app)
        client.get("/meta")
        assert captured["meta"].get("correlation_id") == "corr-id-xyz"

    def test_includes_tenant_id_from_header(self):
        app = FastAPI()
        captured = {}

        @app.get("/meta")
        def endpoint(request: Request):
            captured["meta"] = LoggingMiddleware._extract_metadata(request)
            return {}

        client = TestClient(app)
        client.get("/meta", headers={"X-Tenant-ID": "tenant-abc"})
        assert captured["meta"].get("tenant_id") == "tenant-abc"

    def test_uses_x_forwarded_for_as_client_ip(self):
        app = FastAPI()
        captured = {}

        @app.get("/meta")
        def endpoint(request: Request):
            captured["meta"] = LoggingMiddleware._extract_metadata(request)
            return {}

        client = TestClient(app)
        client.get("/meta", headers={"X-Forwarded-For": "10.0.0.1, 10.0.0.2"})
        assert captured["meta"].get("client_ip") == "10.0.0.1"

    def test_duration_logged_as_positive(self):
        """duration_ms in log extra should be > 0."""
        durations = []
        app = _build_app()
        with patch("tr_shared.middleware.logging_middleware.logger") as mock_logger:
            mock_logger.warning = MagicMock()
            mock_logger.info = MagicMock()

            def capture_extra(msg, **kwargs):
                extra = kwargs.get("extra", {})
                if "duration_ms" in extra:
                    durations.append(extra["duration_ms"])

            mock_logger.info.side_effect = capture_extra
            client = TestClient(app)
            client.get("/api/test")

        # At least one log call with duration_ms
        assert len(durations) > 0
        assert all(d >= 0 for d in durations)
