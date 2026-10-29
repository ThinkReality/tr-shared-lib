import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tr_shared.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadGatewayError,
    BaseAPIException,
    ConflictError,
    ContentTooLargeError,
    DatabaseError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)
from tr_shared.middleware import (
    GlobalErrorHandlerMiddleware,
    UnstorableTextMiddleware,
    register_exception_handlers,
)
from tr_shared.schemas.error_envelope import framework_error_code

UNCODED_ERRORS = [
    pytest.param(ValidationError("bad"), 400, "TEST_VALIDATION_000", id="validation"),
    pytest.param(AuthenticationError(), 401, "TEST_AUTH_000", id="authentication"),
    pytest.param(AuthorizationError(), 403, "TEST_FORBIDDEN_000", id="authorization"),
    pytest.param(NotFoundError("Lead"), 404, "TEST_NOT_FOUND_000", id="not-found"),
    pytest.param(ConflictError(), 409, "TEST_CONFLICT_000", id="conflict"),
    pytest.param(ContentTooLargeError(), 413, "TEST_CONTENT_TOO_LARGE_000", id="too-large"),
    pytest.param(RateLimitError(), 429, "TEST_RATE_LIMIT_000", id="rate-limit"),
    pytest.param(DatabaseError(), 500, "TEST_DATABASE_000", id="database"),
    pytest.param(InternalServerError(), 500, "TEST_INTERNAL_000", id="internal"),
    pytest.param(BadGatewayError(), 502, "TEST_BAD_GATEWAY_000", id="bad-gateway"),
    pytest.param(ServiceUnavailableError(), 503, "TEST_UNAVAILABLE_000", id="unavailable"),
    pytest.param(ServiceTimeoutError(), 504, "TEST_TIMEOUT_000", id="timeout"),
    pytest.param(
        BaseAPIException(status_code=418, error="teapot"), 418, "TEST_HTTP_418", id="base"
    ),
]


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


@pytest.mark.filterwarnings("error::DeprecationWarning")
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


@pytest.mark.parametrize(("error", "status", "code"), UNCODED_ERRORS)
def test_a_shared_error_raised_without_a_code_carries_the_service_prefix(
    error: BaseAPIException, status: int, code: str
) -> None:
    app = _app()

    @app.get("/raise")
    async def raise_it() -> None:
        raise error

    response = TestClient(app, raise_server_exceptions=False).get("/raise")

    assert (response.status_code, response.json()["error"]["code"]) == (status, code)


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
