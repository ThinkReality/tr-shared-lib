import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from tr_shared.exceptions import NotFoundError
from tr_shared.middleware import register_exception_handlers


class _RaisingBody(BaseModel):
    x: str

    @field_validator("x")
    @classmethod
    def _reject(cls, v: str) -> str:
        # A raised ValueError lands in exc.errors()[...]['ctx']['error'] as a live
        # ValueError object — not JSON-serializable.
        raise ValueError("always invalid")


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

    @app.post("/validate-body")
    def _vb(body: _RaisingBody):
        return {"ok": True}

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


def test_field_validator_valueerror_is_422_not_500():
    # Regression: a field_validator that raises ValueError previously produced a 500 —
    # exc.errors() carried the non-serializable ValueError in ctx.error and crashed
    # JSONResponse. jsonable_encoder must coerce it so the body serializes as 422.
    client = TestClient(_make_app(), raise_server_exceptions=False)
    resp = client.post("/validate-body", json={"x": "anything"})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    json.dumps(body["error"]["fields"])  # must be JSON round-trippable


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
