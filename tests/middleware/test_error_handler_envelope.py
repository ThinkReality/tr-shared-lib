from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from tr_shared.middleware.error_handler import GlobalErrorHandlerMiddleware
from tr_shared.schemas.error_envelope import set_error_code_prefix


def _boom(request):
    raise RuntimeError("kaboom")


def test_unhandled_500_uses_nested_envelope():
    app = Starlette(routes=[Route("/boom", _boom)])
    set_error_code_prefix(app, "TEST")
    app.add_middleware(GlobalErrorHandlerMiddleware)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert isinstance(body["error"], dict)
    assert body["error"]["message"] == "Internal server error"
    assert body["error"]["code"] == "TEST_INTERNAL_000"
    assert "correlation_id" in body["error"]
