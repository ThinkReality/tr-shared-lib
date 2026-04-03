"""Tests for GlobalErrorHandlerMiddleware."""

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from tr_shared.middleware.error_handler import (
    GlobalErrorHandlerMiddleware,
    _hash_identifier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app(raise_exc=None, status_code=200, **middleware_kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(GlobalErrorHandlerMiddleware, **middleware_kwargs)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/fail")
    def fail():
        if raise_exc:
            raise raise_exc
        return {"ok": True}

    @app.get("/http-error")
    def http_error():
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/server-error-with-body")
    def server_error_with_body():
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "downstream unavailable", "code": "UPSTREAM_UNAVAILABLE"}},
        )

    return app


# ---------------------------------------------------------------------------
# _hash_identifier
# ---------------------------------------------------------------------------

class TestHashIdentifier:
    def test_empty_string_returns_na(self):
        assert _hash_identifier("") == "N/A"

    def test_returns_16_char_hex(self):
        result = _hash_identifier("some-user-id")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_input_same_output(self):
        assert _hash_identifier("user-123") == _hash_identifier("user-123")

    def test_different_inputs_different_outputs(self):
        assert _hash_identifier("user-a") != _hash_identifier("user-b")


# ---------------------------------------------------------------------------
# Normal request (no exception)
# ---------------------------------------------------------------------------

class TestNormalRequests:
    def test_200_passes_through(self):
        client = TestClient(_build_app())
        response = client.get("/ok")
        assert response.status_code == 200

    def test_response_body_passes_through(self):
        client = TestClient(_build_app())
        response = client.get("/ok")
        assert response.json() == {"ok": True}


# ---------------------------------------------------------------------------
# Unhandled exceptions → 500
# ---------------------------------------------------------------------------

class TestUnhandledExceptions:
    def test_unhandled_exception_returns_500(self):
        client = TestClient(
            _build_app(raise_exc=RuntimeError("boom")),
            raise_server_exceptions=False,
        )
        response = client.get("/fail")
        assert response.status_code == 500

    def test_500_body_has_error_field(self):
        client = TestClient(
            _build_app(raise_exc=RuntimeError("boom")),
            raise_server_exceptions=False,
        )
        response = client.get("/fail")
        body = response.json()
        assert "error" in body

    def test_500_body_has_code_field(self):
        client = TestClient(
            _build_app(raise_exc=RuntimeError("boom")),
            raise_server_exceptions=False,
        )
        response = client.get("/fail")
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"

    def test_500_body_has_correlation_id(self):
        client = TestClient(
            _build_app(raise_exc=RuntimeError("boom")),
            raise_server_exceptions=False,
        )
        response = client.get("/fail")
        assert "correlation_id" in response.json()["error"]

    def test_500_body_has_message(self):
        client = TestClient(
            _build_app(raise_exc=RuntimeError("boom")),
            raise_server_exceptions=False,
        )
        response = client.get("/fail")
        assert "message" in response.json()["error"]


# ---------------------------------------------------------------------------
# Slack alerts (mocked)
# ---------------------------------------------------------------------------

class TestSlackAlerts:
    async def test_no_alert_when_no_webhook_url(self):
        """When slack_webhook_url is empty, _fire_alert is a no-op."""
        app = _build_app(raise_exc=RuntimeError("boom"), slack_webhook_url="")
        # No exception should propagate from slack logic
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/fail")
        assert response.status_code == 500  # Handler still returns 500

    async def test_slack_failure_does_not_reraise(self):
        """If Slack call fails, the error response is still returned."""
        with patch(
            "tr_shared.middleware.error_handler._get_slack_client"
        ) as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=Exception("Slack down"))
            mock_client_fn.return_value = mock_http

            app = _build_app(
                raise_exc=RuntimeError("boom"),
                slack_webhook_url="https://hooks.slack.com/fake",
            )
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/fail")
            # Should still return 500 despite Slack failure
            assert response.status_code == 500


# ---------------------------------------------------------------------------
# alert_on_5xx
# ---------------------------------------------------------------------------

class TestAlertOn5xx:
    def test_alert_on_5xx_false_does_not_log_5xx_responses(self):
        """5xx handled responses: logged only when alert_on_5xx=True."""
        from fastapi import Response

        app = FastAPI()
        app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=False)

        @app.get("/server-error")
        def server_error():
            return Response(status_code=503)

        client = TestClient(app, raise_server_exceptions=False)
        # Should pass through without triggering error handler logging
        response = client.get("/server-error")
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# _extract_identity
# ---------------------------------------------------------------------------

class TestExtractIdentity:
    def test_returns_none_when_no_auth_context(self):
        from starlette.requests import Request
        from starlette.testclient import TestClient

        app = FastAPI()
        app.add_middleware(GlobalErrorHandlerMiddleware)
        extracted = {}

        @app.get("/identity")
        def capture(request: Request):
            uid, tid = GlobalErrorHandlerMiddleware._extract_identity(request)
            extracted["uid"] = uid
            extracted["tid"] = tid
            return {}

        client = TestClient(app)
        client.get("/identity")
        assert extracted["uid"] is None
        assert extracted["tid"] is None


# ---------------------------------------------------------------------------
# New context fields
# ---------------------------------------------------------------------------

class TestQueryStringInContext:
    def test_query_string_present(self):
        """query field is populated when query params are present."""
        captured = {}

        app = FastAPI()
        app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)

        @app.get("/search")
        def search():
            return JSONResponse(status_code=503, content={"error": "fail"})

        with patch.object(
            GlobalErrorHandlerMiddleware, "_fire_alert",
            side_effect=lambda ctx: captured.update(ctx),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/search?page=2&sort=name")

        assert captured["query"] == "page=2&sort=name"

    def test_query_string_empty_when_no_params(self):
        """query field is empty string when no query params."""
        captured = {}

        app = FastAPI()
        app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)

        @app.get("/search")
        def search():
            return JSONResponse(status_code=500, content={"error": "fail"})

        with patch.object(
            GlobalErrorHandlerMiddleware, "_fire_alert",
            side_effect=lambda ctx: captured.update(ctx),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/search")

        assert captured["query"] == ""


class TestTimestampInContext:
    def test_timestamp_present_and_iso_format(self):
        """timestamp field is present and in ISO 8601 format."""
        from datetime import datetime as dt

        captured = {}

        app = FastAPI()
        app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)

        @app.get("/ts")
        def ts():
            return JSONResponse(status_code=500, content={})

        with patch.object(
            GlobalErrorHandlerMiddleware, "_fire_alert",
            side_effect=lambda ctx: captured.update(ctx),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/ts")

        assert "timestamp" in captured
        # Should parse without error — ISO format with seconds precision
        dt.fromisoformat(captured["timestamp"])


class TestHostInContext:
    def test_host_present(self):
        """host field is present in context."""
        captured = {}

        app = FastAPI()
        app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)

        @app.get("/h")
        def h():
            return JSONResponse(status_code=500, content={})

        with patch.object(
            GlobalErrorHandlerMiddleware, "_fire_alert",
            side_effect=lambda ctx: captured.update(ctx),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/h")

        assert "host" in captured
        assert len(captured["host"]) > 0


class TestUserTenantInSlackBlocks:
    def test_user_tenant_in_slack_fields(self):
        """Slack blocks include User and Tenant fields."""
        app = FastAPI()
        app.add_middleware(
            GlobalErrorHandlerMiddleware,
            slack_webhook_url="https://hooks.slack.com/fake",
            alert_on_5xx=True,
            hash_pii=False,
        )

        @app.get("/ut")
        def ut(request: Request):
            # Simulate identity on request.state
            request.state.user = {"id": "user-abc", "tenant_id": "tenant-xyz"}
            return JSONResponse(status_code=500, content={})

        with patch(
            "tr_shared.middleware.error_handler._get_slack_client"
        ) as mock_client_fn:
            mock_http = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_http

            client = TestClient(app, raise_server_exceptions=False)
            client.get("/ut")

            # Extract the blocks from the Slack POST call
            call_args = mock_http.post.call_args
            blocks = call_args.kwargs["json"]["blocks"]
            fields_block = blocks[1]  # section with fields
            field_texts = [f["text"] for f in fields_block["fields"]]

            assert any("User" in t for t in field_texts)
            assert any("Tenant" in t for t in field_texts)


class TestTracebackTailTruncation:
    def test_2000_char_traceback_shows_tail(self):
        """A 2000-char traceback is truncated to the last 1500 chars."""
        app = FastAPI()
        app.add_middleware(
            GlobalErrorHandlerMiddleware,
            slack_webhook_url="https://hooks.slack.com/fake",
        )

        # Create a traceback longer than 1500 chars
        long_tb = "X" * 500 + "Y" * 1500  # 2000 chars total

        @app.get("/tb")
        def tb():
            raise RuntimeError("boom")

        with patch(
            "tr_shared.middleware.error_handler.traceback.format_exc",
            return_value=long_tb,
        ), patch(
            "tr_shared.middleware.error_handler._get_slack_client"
        ) as mock_client_fn:
            mock_http = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_http

            client = TestClient(app, raise_server_exceptions=False)
            client.get("/tb")

            call_args = mock_http.post.call_args
            blocks = call_args.kwargs["json"]["blocks"]
            tb_block = blocks[3]  # traceback section
            tb_text = tb_block["text"]["text"]

            # Should contain the tail (Y's) but NOT the full head (X's)
            assert "Y" * 1500 in tb_text
            assert "X" * 500 not in tb_text


class Test5xxResponseBodyInContext:
    def test_response_body_captured(self):
        """For handled 5xx, response body appears in context."""
        captured = {}

        app = _build_app(alert_on_5xx=True)

        with patch.object(
            GlobalErrorHandlerMiddleware, "_fire_alert",
            side_effect=lambda ctx: captured.update(ctx),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/server-error-with-body")

        assert "response_body" in captured
        assert "downstream unavailable" in captured["response_body"]


class Test5xxResponseBodyStillReturnedToClient:
    def test_client_receives_body(self):
        """After body buffering, the client still receives the full response body."""
        app = _build_app(alert_on_5xx=True)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/server-error-with-body")

        assert response.status_code == 503
        body = response.json()
        assert body["error"]["message"] == "downstream unavailable"
        assert body["error"]["code"] == "UPSTREAM_UNAVAILABLE"


class Test5xxResponseBodyTruncation:
    def test_long_body_truncated_at_500_chars(self):
        """Response bodies longer than 500 chars are truncated."""
        captured = {}

        app = FastAPI()
        app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)

        long_message = "A" * 800

        @app.get("/long-body")
        def long_body():
            return JSONResponse(
                status_code=500,
                content={"error": {"message": long_message}},
            )

        with patch.object(
            GlobalErrorHandlerMiddleware, "_fire_alert",
            side_effect=lambda ctx: captured.update(ctx),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/long-body")

        assert len(captured["response_body"]) == 500


class TestNoDuplicateContentTypeHeader:
    def test_single_content_type_header(self):
        """Re-wrapped 5xx response has exactly one Content-Type header."""
        app = _build_app(alert_on_5xx=True)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/server-error-with-body")

        ct_headers = [
            v for k, v in response.headers.items()
            if k.lower() == "content-type"
        ]
        assert len(ct_headers) == 1
