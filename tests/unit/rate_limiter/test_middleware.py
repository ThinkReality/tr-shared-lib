"""Tests for RateLimitMiddleware (BaseHTTPMiddleware)."""

import time
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tr_shared.rate_limiter.core import RateLimiter
from tr_shared.rate_limiter.middleware import RateLimitMiddleware
from tr_shared.rate_limiter.schemas import (
    FailMode,
    RateLimitConfig,
    RateLimitInfo,
    RateLimitResult,
    WindowConfig,
)


def _allowed_info(limit: int = 100, remaining: int = 99) -> RateLimitInfo:
    return RateLimitInfo(
        results=[
            RateLimitResult(
                allowed=True, limit=limit, remaining=remaining,
                reset_at=int(time.time()) + 60, retry_after=0,
            )
        ],
        is_blocked=False,
    )


def _blocked_info(limit: int = 100, retry_after: int = 30) -> RateLimitInfo:
    return RateLimitInfo(
        results=[
            RateLimitResult(
                allowed=False, limit=limit, remaining=0,
                reset_at=int(time.time()) + retry_after, retry_after=retry_after,
            )
        ],
        is_blocked=True,
    )


def _build_app(limiter: RateLimiter, config: RateLimitConfig | None = None, **kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter, config=config, **kwargs)

    @app.get("/api/test")
    def endpoint():
        return {"ok": True}

    @app.post("/api/test")
    def post_endpoint():
        return {"ok": True}

    return app


class TestExcludedPaths:
    async def test_health_path_bypasses_rate_limiting(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        app = _build_app(limiter)

        @app.get("/health")
        def health():
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/health")
        limiter.check.assert_not_called()

    async def test_docs_path_bypasses_rate_limiting(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        app = _build_app(limiter)
        client = TestClient(app)
        client.get("/docs")
        limiter.check.assert_not_called()

    async def test_custom_excluded_path_bypasses(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            excluded_paths=frozenset({"/internal"}),
        )

        @app.get("/internal/status")
        def internal():
            return {"ok": True}

        client = TestClient(app)
        client.get("/internal/status")
        limiter.check.assert_not_called()


class TestAllowedRequests:
    async def test_allowed_request_returns_200(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        limiter.build_key = MagicMock(return_value="test:key")
        app = _build_app(limiter)
        client = TestClient(app)
        response = client.get("/api/test")
        assert response.status_code == 200

    async def test_allowed_response_has_rate_limit_headers(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info(limit=100, remaining=95))
        limiter.build_key = MagicMock(return_value="test:key")
        app = _build_app(limiter)
        client = TestClient(app)
        response = client.get("/api/test")
        assert "x-ratelimit-limit" in response.headers
        assert "x-ratelimit-remaining" in response.headers


class TestBlockedRequests:
    async def test_blocked_request_returns_429(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_blocked_info())
        limiter.build_key = MagicMock(return_value="test:key")
        app = _build_app(limiter)
        client = TestClient(app)
        response = client.get("/api/test")
        assert response.status_code == 429

    async def test_blocked_response_has_retry_after_header(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_blocked_info(retry_after=30))
        limiter.build_key = MagicMock(return_value="test:key")
        app = _build_app(limiter)
        client = TestClient(app)
        response = client.get("/api/test")
        assert "retry-after" in response.headers

    async def test_blocked_response_body_has_error_field(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_blocked_info())
        limiter.build_key = MagicMock(return_value="test:key")
        app = _build_app(limiter)
        client = TestClient(app)
        response = client.get("/api/test")
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"


class TestMethodFiltering:
    async def test_get_bypasses_when_methods_is_post_only(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        config = RateLimitConfig(
            windows=[WindowConfig(limit=5, window_seconds=60)],
            methods=["POST"],
        )
        app = _build_app(limiter, config=config)
        client = TestClient(app)
        client.get("/api/test")
        limiter.check.assert_not_called()

    async def test_post_is_checked_when_methods_is_post_only(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        limiter.build_key = MagicMock(return_value="test:key")
        config = RateLimitConfig(
            windows=[WindowConfig(limit=5, window_seconds=60)],
            methods=["POST"],
        )
        app = _build_app(limiter, config=config)
        client = TestClient(app)
        client.post("/api/test")
        limiter.check.assert_called_once()


class TestIpWhitelist:
    async def test_whitelisted_ip_bypasses_rate_limiting(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        app = FastAPI()
        # TestClient uses "testclient" as the client host
        app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            whitelist_ips=["testclient"],
        )

        @app.get("/api/test")
        def endpoint():
            return {"ok": True}

        client = TestClient(app)
        client.get("/api/test")
        limiter.check.assert_not_called()


class TestCustomIdentifierExtractor:
    async def test_custom_extractor_is_called(self):
        limiter = RateLimiter()
        limiter.check = AsyncMock(return_value=_allowed_info())
        limiter.build_key = MagicMock(return_value="custom:key")

        custom_extractor = MagicMock(return_value="custom-identifier")
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            identifier_extractor=custom_extractor,
        )

        @app.get("/api/test")
        def endpoint():
            return {"ok": True}

        client = TestClient(app)
        client.get("/api/test")
        custom_extractor.assert_called()


# Avoid F821 for MagicMock
from unittest.mock import MagicMock  # noqa: E402
