import asyncio
import json
import logging

import httpx
import pytest
from fastapi import FastAPI

from tr_shared.exceptions import BaseAPIException
from tr_shared.middleware import (
    GlobalErrorHandlerMiddleware,
    error_handler,
    register_exception_handlers,
)

WEBHOOK = "https://hooks.slack.com/services/test"


@pytest.fixture
async def slack_posts(monkeypatch):
    posts: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        posts.append(json.loads(request.content))
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    monkeypatch.setattr(error_handler, "_slack_client", client)
    yield posts
    await client.aclose()


def _app(rate_limit: int = 5) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/fail")
    async def fail(status: int, code: str | None = None, retry_after: int | None = None):
        headers = None if retry_after is None else {"Retry-After": str(retry_after)}
        raise BaseAPIException(status_code=status, error="failed", code=code, headers=headers)

    app.add_middleware(
        GlobalErrorHandlerMiddleware,
        service_name="svc",
        slack_webhook_url=WEBHOOK,
        rate_limit=rate_limit,
    )
    return app


async def _get(app: FastAPI, **params: str | int) -> httpx.Response:
    pending_before = set(error_handler._pending_alerts)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/fail", params=params)
    await asyncio.gather(*(error_handler._pending_alerts - pending_before))
    return response


def _posts_mentioning(posts: list[dict], code: str) -> list[dict]:
    return [post for post in posts if code in json.dumps(post)]


async def test_a_503_that_tells_the_client_when_to_retry_does_not_page(slack_posts):
    response = await _get(_app(), status=503, code="GATEWAY_SERVICE_UNAVAILABLE_001", retry_after=1)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert slack_posts == []


async def test_a_503_that_tells_the_client_when_to_retry_is_still_logged(slack_posts, caplog):
    with caplog.at_level(logging.ERROR, logger=error_handler.logger.name):
        await _get(_app(), status=503, code="GATEWAY_SERVICE_UNAVAILABLE_001", retry_after=1)

    handled = [r for r in caplog.records if r.getMessage() == "Handled 5xx response"]
    assert [record.status_code for record in handled] == [503]


async def test_a_503_without_retry_after_pages(slack_posts):
    await _get(_app(), status=503, code="CRM_SERVICE_UNAVAILABLE_001")

    assert len(slack_posts) == 1


@pytest.mark.parametrize("status", [500, 502, 504])
async def test_retry_after_exempts_only_a_503(slack_posts, status):
    await _get(_app(), status=status, code="SVC_FAILED_001", retry_after=1)

    assert len(slack_posts) == 1


async def test_an_error_code_pages_at_most_rate_limit_times(slack_posts):
    app = _app(rate_limit=2)

    for _ in range(3):
        await _get(app, status=503, code="SVC_BUSY_001")

    assert len(slack_posts) == 2


async def test_noise_from_one_error_code_does_not_mute_another(slack_posts):
    app = _app(rate_limit=2)

    for _ in range(3):
        await _get(app, status=503, code="SVC_BUSY_001")
    await _get(app, status=503, code="SVC_DOWN_001")

    assert len(_posts_mentioning(slack_posts, "SVC_DOWN_001")) == 1


async def test_responses_without_a_code_share_one_budget_per_status(slack_posts):
    app = _app(rate_limit=2)

    for _ in range(3):
        await _get(app, status=503)
    await _get(app, status=502)

    assert len(slack_posts) == 3
