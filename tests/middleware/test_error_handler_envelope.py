from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from tr_shared.middleware.error_handler import GlobalErrorHandlerMiddleware


def _boom(request):
    raise RuntimeError("kaboom")


def test_unhandled_500_uses_nested_envelope():
    app = Starlette(routes=[Route("/boom", _boom)])
    app.add_middleware(GlobalErrorHandlerMiddleware)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert isinstance(body["error"], dict)
    assert body["error"]["message"] == "Internal server error"
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "correlation_id" in body["error"]
