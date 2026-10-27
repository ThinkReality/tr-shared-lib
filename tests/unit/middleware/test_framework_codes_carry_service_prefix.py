import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tr_shared.middleware import (
    GlobalErrorHandlerMiddleware,
    UnstorableTextMiddleware,
    register_exception_handlers,
)
from tr_shared.schemas.error_envelope import framework_error_code


class Item(BaseModel):
    count: int


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app, code_prefix="TEST")
    app.add_middleware(UnstorableTextMiddleware)
    app.add_middleware(GlobalErrorHandlerMiddleware, service_name="test", alert_on_5xx=False)

    @app.post("/items")
    async def create(item: Item) -> dict[str, int]:
        return {"count": item.count}

    @app.get("/search")
    async def search(q: str) -> dict[str, str]:
        return {"q": q}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("unexpected")

    @app.get("/unchanged")
    async def unchanged() -> None:
        raise HTTPException(status_code=304)

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def test_a_body_that_fails_validation_carries_the_service_prefix(client: TestClient) -> None:
    response = client.post("/items", json={"count": "many"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "TEST_VALIDATION_000"
    assert error["fields"][0]["loc"] == ["body", "count"]


def test_unstorable_text_carries_the_service_prefix(client: TestClient) -> None:
    response = client.get("/search", params={"q": "a\x00b"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEST_VALIDATION_000"


def test_an_unknown_route_answers_the_canonical_envelope(client: TestClient) -> None:
    response = client.get("/nowhere")

    assert response.status_code == 404
    assert response.json() == {"error": {"message": "Not Found", "code": "TEST_HTTP_404"}}


def test_a_wrong_method_answers_the_canonical_envelope_and_keeps_allow(client: TestClient) -> None:
    response = client.delete("/items")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "TEST_HTTP_405"
    assert response.headers["allow"] == "POST"


def test_a_status_without_a_body_answers_without_one(client: TestClient) -> None:
    response = client.get("/unchanged")

    assert response.status_code == 304
    assert response.content == b""


def test_an_unhandled_exception_carries_the_service_prefix(client: TestClient) -> None:
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "TEST_INTERNAL_000"


def test_the_registrar_requires_a_prefix() -> None:
    with pytest.raises(TypeError, match="code_prefix"):
        register_exception_handlers(FastAPI())


@pytest.mark.parametrize("prefix", ["media", "MEDIA_", "", "ME DIA", "MEDIA1"])
def test_the_registrar_refuses_a_prefix_outside_the_contract(prefix: str) -> None:
    with pytest.raises(ValueError, match="code_prefix"):
        register_exception_handlers(FastAPI(), code_prefix=prefix)


def test_a_code_cannot_be_built_for_an_app_that_never_registered() -> None:
    with pytest.raises(RuntimeError, match="register_exception_handlers"):
        framework_error_code(FastAPI(), "VALIDATION_000")
