from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from tr_shared.contracts import UNAVAILABLE_RETRY_AFTER_SECONDS, DatabaseOutageCode
from tr_shared.db import DatabaseTimeoutError, DatabaseUnavailableError
from tr_shared.exceptions import ServiceUnavailableError
from tr_shared.middleware import GlobalErrorHandlerMiddleware, register_exception_handlers

_OUTAGES = [
    DatabaseUnavailableError("refused", code=DatabaseOutageCode.CONNECT_FAILED),
    DatabaseUnavailableError("closed", code=DatabaseOutageCode.CONNECTION_LOST),
    PoolTimeoutError("QueuePool limit reached"),
    DatabaseTimeoutError("cap"),
]


def _app(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise exc

    return app


def _get(app: FastAPI):
    return TestClient(app, raise_server_exceptions=False).get("/boom")


@pytest.mark.parametrize(
    "exc, code",
    [
        (_OUTAGES[0], DatabaseOutageCode.CONNECT_FAILED),
        (_OUTAGES[1], DatabaseOutageCode.CONNECTION_LOST),
        (_OUTAGES[2], DatabaseOutageCode.POOL_EXHAUSTED),
    ],
)
def test_an_unreachable_database_is_503_with_retry_after(exc, code):
    response = _get(_app(exc))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == code
    assert response.headers["retry-after"] == str(UNAVAILABLE_RETRY_AFTER_SECONDS)


def test_a_statement_over_its_cap_is_504():
    response = _get(_app(_OUTAGES[3]))
    assert response.status_code == 504
    assert response.json()["error"]["code"] == DatabaseOutageCode.STATEMENT_TIMEOUT


def test_other_database_errors_are_left_alone():
    response = _get(_app(IntegrityError("INSERT", {}, Exception("duplicate key"))))
    assert response.status_code == 500
    assert not any(code in response.text for code in DatabaseOutageCode)


@pytest.mark.parametrize("exc", _OUTAGES)
def test_database_outages_do_not_page_slack(exc):
    app = _app(exc)
    app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)
    fired: list[dict] = []
    with patch.object(GlobalErrorHandlerMiddleware, "_fire_alert", side_effect=fired.append):
        _get(app)
    assert fired == []


def test_other_5xx_responses_still_page_slack():
    app = _app(ServiceUnavailableError())
    app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)
    fired: list[dict] = []
    with patch.object(GlobalErrorHandlerMiddleware, "_fire_alert", side_effect=fired.append):
        _get(app)
    assert len(fired) == 1


def test_a_5xx_whose_code_is_not_a_string_still_pages_slack():
    app = FastAPI()

    @app.get("/boom")
    async def boom():
        return JSONResponse(status_code=502, content={"error": {"code": ["not", "a", "string"]}})

    app.add_middleware(GlobalErrorHandlerMiddleware, alert_on_5xx=True)
    fired: list[dict] = []
    with patch.object(GlobalErrorHandlerMiddleware, "_fire_alert", side_effect=fired.append):
        response = _get(app)
    assert response.status_code == 502
    assert len(fired) == 1
