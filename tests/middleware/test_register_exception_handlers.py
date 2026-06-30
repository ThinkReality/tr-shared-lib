from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from tr_shared.exceptions import NotFoundError
from tr_shared.middleware import register_exception_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/notfound")
    def _nf():
        raise NotFoundError(resource="Lead", code="LEAD_NOT_FOUND_001")

    @app.get("/http")
    def _http():
        raise HTTPException(status_code=403, detail="nope")

    @app.get("/validate/{n}")
    def _v(n: int):
        return {"n": n}

    return app


def test_base_api_exception_nested_envelope():
    client = TestClient(_make_app(), raise_server_exceptions=False)
    resp = client.get("/notfound")
    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "Lead not found"
    assert resp.json()["error"]["code"] == "LEAD_NOT_FOUND_001"


def test_plain_http_exception_nested_envelope():
    client = TestClient(_make_app(), raise_server_exceptions=False)
    resp = client.get("/http")
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "nope"
    assert resp.json()["error"]["code"] == "HTTP_403"


def test_validation_error_nested_envelope():
    client = TestClient(_make_app(), raise_server_exceptions=False)
    resp = client.get("/validate/not-an-int")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(resp.json()["error"]["fields"], list)


def test_base_api_exception_injects_correlation_id():
    app = FastAPI()
    register_exception_handlers(app)

    @app.middleware("http")
    async def _set_cid(request, call_next):
        request.state.correlation_id = "cid-123"
        return await call_next(request)

    @app.get("/notfound")
    def _nf():
        raise NotFoundError(resource="Lead", code="LEAD_NOT_FOUND_001")

    resp = TestClient(app, raise_server_exceptions=False).get("/notfound")
    assert resp.status_code == 404
    assert resp.json()["error"]["correlation_id"] == "cid-123"
