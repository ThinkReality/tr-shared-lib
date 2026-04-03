"""Tests for PersistenceMiddleware."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tr_shared.monitoring.persistence import PersistenceMiddleware


def _make_app():
    app = FastAPI()
    app.add_middleware(
        PersistenceMiddleware,
        service_name="test-svc",
        redis_url="redis://localhost:6379",
    )

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


class TestInit:
    def test_stores_service_name(self):
        app = FastAPI()
        mw = PersistenceMiddleware(app, service_name="my-svc")
        assert mw.service_name == "my-svc"

    def test_stores_redis_url(self):
        app = FastAPI()
        mw = PersistenceMiddleware(app, redis_url="redis://myhost:6379")
        assert mw.redis_url == "redis://myhost:6379"

    def test_default_excluded_paths_include_health(self):
        app = FastAPI()
        mw = PersistenceMiddleware(app)
        assert "/health" in mw.excluded_paths

    def test_custom_excluded_paths_override_defaults(self):
        app = FastAPI()
        mw = PersistenceMiddleware(app, excluded_paths=frozenset({"/custom"}))
        assert "/custom" in mw.excluded_paths
        assert "/health" not in mw.excluded_paths


class TestDispatch:
    def test_excluded_path_does_not_call_persist(self):
        app = _make_app()
        mock_persist = AsyncMock()
        with TestClient(app) as client:
            with __import__("unittest.mock", fromlist=["patch"]).patch.object(
                PersistenceMiddleware, "_persist_record", mock_persist
            ):
                client.get("/health")
                mock_persist.assert_not_awaited()

    def test_non_excluded_path_calls_persist_record(self):
        app = _make_app()
        mock_persist = AsyncMock()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            PersistenceMiddleware, "_persist_record", mock_persist
        ):
            client = TestClient(app)
            client.get("/api/test")
            mock_persist.assert_awaited_once()


class TestExtractIdentity:
    def test_extracts_from_auth_context(self):
        auth_ctx = MagicMock()
        auth_ctx.user_id = "user-123"
        auth_ctx.tenant_id = "tenant-456"
        state = MagicMock()
        state.auth_context = auth_ctx
        request = MagicMock()
        request.state = state

        user_id, tenant_id = PersistenceMiddleware._extract_identity(request)
        assert user_id == "user-123"
        assert tenant_id == "tenant-456"

    def test_falls_back_to_headers(self):
        state = MagicMock()
        state.auth_context = None
        state.user = None
        request = MagicMock()
        request.state = state
        request.headers = {"x-tenant-id": "t-999", "x-user-id": "u-888"}

        user_id, tenant_id = PersistenceMiddleware._extract_identity(request)
        assert user_id == "u-888"
        assert tenant_id == "t-999"

    def test_returns_none_when_no_identity(self):
        state = MagicMock()
        state.auth_context = None
        state.user = None
        request = MagicMock()
        request.state = state
        request.headers = {}

        user_id, tenant_id = PersistenceMiddleware._extract_identity(request)
        assert user_id is None
        assert tenant_id is None

    def test_extracts_from_legacy_user_dict(self):
        state = MagicMock()
        state.auth_context = None
        state.user = {"id": "usr-77", "tenant_id": "ten-88"}
        request = MagicMock()
        request.state = state

        user_id, tenant_id = PersistenceMiddleware._extract_identity(request)
        assert user_id == "usr-77"
        assert tenant_id == "ten-88"


class TestGetContentLength:
    def test_returns_int_from_header(self):
        request = MagicMock()
        request.headers = {"content-length": "1024"}
        assert PersistenceMiddleware._get_content_length(request) == 1024

    def test_returns_none_when_header_missing(self):
        request = MagicMock()
        request.headers = {}
        assert PersistenceMiddleware._get_content_length(request) is None

    def test_returns_none_for_invalid_value(self):
        request = MagicMock()
        request.headers = {"content-length": "not-a-number"}
        assert PersistenceMiddleware._get_content_length(request) is None
