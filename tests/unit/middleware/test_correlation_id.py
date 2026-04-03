"""Tests for CorrelationIDMiddleware."""

import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tr_shared.middleware.correlation_id import CorrelationIDMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/test")
    def endpoint(request: Request):
        return {"correlation_id": getattr(request.state, "correlation_id", None)}

    return app


class TestCorrelationIDMiddleware:
    def test_generates_correlation_id_when_absent(self):
        client = TestClient(_build_app())
        response = client.get("/test")
        assert "x-correlation-id" in response.headers
        assert len(response.headers["x-correlation-id"]) > 0

    def test_generated_id_is_valid_uuid(self):
        client = TestClient(_build_app())
        response = client.get("/test")
        cid = response.headers["x-correlation-id"]
        uuid.UUID(cid)  # Raises ValueError if not a valid UUID

    def test_propagates_existing_correlation_id(self):
        client = TestClient(_build_app())
        existing_id = "my-custom-correlation-id-123"
        response = client.get("/test", headers={"X-Correlation-ID": existing_id})
        assert response.headers["x-correlation-id"] == existing_id

    def test_response_always_has_correlation_id_header(self):
        client = TestClient(_build_app())
        # No X-Correlation-ID in request
        response = client.get("/test")
        assert "x-correlation-id" in response.headers

    def test_correlation_id_set_in_request_state(self):
        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)
        captured = {}

        @app.get("/capture")
        def capture(request: Request):
            captured["cid"] = getattr(request.state, "correlation_id", None)
            return {}

        client = TestClient(app)
        client.get("/capture")
        assert captured["cid"] is not None
        assert len(captured["cid"]) > 0

    def test_existing_id_stored_in_request_state(self):
        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)
        captured = {}

        @app.get("/capture")
        def capture(request: Request):
            captured["cid"] = getattr(request.state, "correlation_id", None)
            return {}

        client = TestClient(app)
        client.get("/capture", headers={"X-Correlation-ID": "explicit-id-abc"})
        assert captured["cid"] == "explicit-id-abc"

    def test_different_requests_get_different_ids(self):
        client = TestClient(_build_app())
        r1 = client.get("/test")
        r2 = client.get("/test")
        assert r1.headers["x-correlation-id"] != r2.headers["x-correlation-id"]

    def test_response_id_matches_request_id(self):
        client = TestClient(_build_app())
        my_id = "test-id-xyz"
        response = client.get("/test", headers={"X-Correlation-ID": my_id})
        assert response.headers["x-correlation-id"] == my_id
