"""Tests for create_rate_limit_dependency and rate_limit decorator."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from tr_shared.rate_limiter.core import RateLimiter, default_identifier_extractor
from tr_shared.rate_limiter.dependency import (
    create_rate_limit_dependency,
    rate_limit,
)
from tr_shared.rate_limiter.schemas import (
    FailMode,
    RateLimitInfo,
    RateLimitResult,
)


def _allowed_info() -> RateLimitInfo:
    return RateLimitInfo(
        results=[
            RateLimitResult(
                allowed=True, limit=100, remaining=99,
                reset_at=int(time.time()) + 60, retry_after=0,
            )
        ],
        is_blocked=False,
    )


def _blocked_info(retry_after: int = 30) -> RateLimitInfo:
    return RateLimitInfo(
        results=[
            RateLimitResult(
                allowed=False, limit=100, remaining=0,
                reset_at=int(time.time()) + retry_after, retry_after=retry_after,
            )
        ],
        is_blocked=True,
    )


def _make_request(ip: str = "1.2.3.4", user_id: str | None = None) -> Request:
    """Build a mock Request with controlled IP and optional auth_context."""
    mock_client = MagicMock()
    mock_client.host = ip
    request = MagicMock(spec=Request)
    request.client = mock_client
    request.url.path = "/api/test"
    request.headers = {}

    if user_id:
        auth_ctx = MagicMock()
        auth_ctx.user_id = user_id
        request.state.auth_context = auth_ctx
    else:
        request.state = MagicMock(spec=[])

    return request


class TestGetIdentifier:
    def test_uses_user_id_from_auth_context(self):
        request = _make_request(ip="1.2.3.4", user_id="user-uuid-123")
        identifier = default_identifier_extractor(request)
        assert identifier == "user-uuid-123"

    def test_falls_back_to_ip_when_no_auth_context(self):
        request = _make_request(ip="10.20.30.40")
        identifier = default_identifier_extractor(request)
        assert identifier == "10.20.30.40"

    def test_returns_unknown_when_no_client(self):
        request = MagicMock(spec=Request)
        request.client = None
        request.headers = {}
        request.state = MagicMock(spec=[])
        identifier = default_identifier_extractor(request)
        assert identifier == "unknown"

    def test_uses_x_forwarded_for_when_present(self):
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "10.0.0.1"
        request.headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
        request.state = MagicMock(spec=[])
        identifier = default_identifier_extractor(request)
        assert identifier == "203.0.113.5"

    def test_uses_x_real_ip_when_present(self):
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "10.0.0.1"
        request.headers = {"X-Real-IP": "203.0.113.10"}
        request.state = MagicMock(spec=[])
        identifier = default_identifier_extractor(request)
        assert identifier == "203.0.113.10"


class TestCreateRateLimitDependency:
    def test_returns_callable(self):
        limiter = RateLimiter()
        dep = create_rate_limit_dependency(limiter, limit=10, window=60)
        assert callable(dep)

    async def test_allows_request_under_limit(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        limiter.build_key = MagicMock(return_value="test:key")
        dep = create_rate_limit_dependency(limiter, limit=10, window=60)

        request = _make_request()
        # Should not raise
        await dep(request)

    async def test_raises_429_when_blocked(self):
        from fastapi import HTTPException

        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_blocked_info(retry_after=30))
        limiter.build_key = MagicMock(return_value="test:key")
        dep = create_rate_limit_dependency(limiter, limit=10, window=60)

        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert exc_info.value.status_code == 429

    async def test_429_has_retry_after_header(self):
        from fastapi import HTTPException

        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_blocked_info(retry_after=45))
        limiter.build_key = MagicMock(return_value="test:key")
        dep = create_rate_limit_dependency(limiter, limit=10, window=60)

        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert "Retry-After" in exc_info.value.headers

    async def test_stores_rate_limit_info_on_request_state(self):
        limiter = RateLimiter()
        info = _allowed_info()
        limiter.check = AsyncMock(return_value=info)
        limiter.build_key = MagicMock(return_value="test:key")
        dep = create_rate_limit_dependency(limiter, limit=10, window=60)

        request = _make_request()
        await dep(request)
        assert request.state.rate_limit_info is info

    def test_dependency_works_as_fastapi_depends(self):
        """Smoke-test that the dependency integrates with FastAPI."""
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        limiter.build_key = MagicMock(return_value="test:key")
        dep = create_rate_limit_dependency(limiter, limit=10, window=60)

        app = FastAPI()

        @app.get("/webhook")
        async def webhook(_=Depends(dep)):
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/webhook")
        assert response.status_code == 200


class TestRateLimitDecorator:
    async def test_allows_call_when_under_limit(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        limiter.build_key = MagicMock(return_value="test:key")

        @rate_limit(limiter, limit=10, window=60)
        async def handler(request: Request):
            return "ok"

        request = _make_request()
        result = await handler(request)
        assert result == "ok"

    async def test_raises_429_when_blocked(self):
        from fastapi import HTTPException

        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_blocked_info())
        limiter.build_key = MagicMock(return_value="test:key")

        @rate_limit(limiter, limit=10, window=60)
        async def handler(request: Request):
            return "ok"

        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            await handler(request)
        assert exc_info.value.status_code == 429

    async def test_passes_through_when_no_request_found(self):
        """Decorator should call function normally when no Request is in args."""
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())

        @rate_limit(limiter, limit=10, window=60)
        async def handler():
            return "no-request"

        # No Request arg — should not raise, just call the function
        result = await handler()
        assert result == "no-request"
