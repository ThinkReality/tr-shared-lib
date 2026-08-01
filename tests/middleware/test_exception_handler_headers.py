"""Error responses must carry the exception's headers.

Both handlers previously built JSONResponse with no headers= argument, so
RateLimitError's Retry-After and every 401's WWW-Authenticate challenge were
silently dropped in all 8 services. RateLimitError's own docstring requires
the handler to surface self.headers; nothing enforced it until this file.
"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from tr_shared.exceptions import AuthenticationError, RateLimitError
from tr_shared.middleware import register_exception_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/rate-limited")
    async def rate_limited() -> None:
        raise RateLimitError(detail="slow down", retry_after=42)

    @app.get("/needs-auth")
    async def needs_auth() -> None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/needs-auth-typed")
    async def needs_auth_typed() -> None:
        raise AuthenticationError(
            detail="Authentication required",
            code="AUTHLIB_AUTH_001",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/plain-403")
    async def plain_403() -> None:
        raise HTTPException(status_code=403, detail="nope")

    @app.get("/forged-transport-headers")
    async def forged_transport_headers() -> None:
        raise HTTPException(
            status_code=400,
            detail="bad request",
            headers={
                "Content-Length": "99999",
                "Content-Type": "text/plain",
                "Retry-After": "5",
            },
        )

    return TestClient(app, raise_server_exceptions=False)


def test_base_api_exception_handler_emits_retry_after() -> None:
    response = _client().get("/rate-limited")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"


def test_http_exception_handler_emits_www_authenticate() -> None:
    response = _client().get("/needs-auth")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_typed_authentication_error_emits_www_authenticate() -> None:
    """RFC 9110 §11.6.1 requires a challenge on every 401.

    ``BaseAPIException`` took no ``headers`` argument until this change, so
    converting shared-auth-lib's raw ``HTTPException`` 401 to the typed exception
    would have silently dropped the fleet's only ``WWW-Authenticate`` header —
    ``auth_dependencies.py`` is its sole producer, and nothing asserted it there.
    """
    response = _client().get("/needs-auth-typed")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "AUTHLIB_AUTH_001"


def test_exception_without_headers_still_responds() -> None:
    """headers=None must not blow up JSONResponse."""
    response = _client().get("/plain-403")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HTTP_403"


def test_envelope_is_unchanged_by_the_header_fix() -> None:
    """The body is the contract; only headers were missing."""
    body = _client().get("/rate-limited").json()

    assert body["error"]["message"] == "Rate limit exceeded"
    assert body["error"]["code"] == "RATE_LIMIT_001"
    assert body["error"]["detail"] == "slow down"


def test_exception_cannot_override_transport_headers() -> None:
    """A forged Content-Length larger than the real body blocks an HTTP/1.1 client
    waiting for bytes that never arrive. JSONResponse must own this header, never
    the exception."""
    response = _client().get("/forged-transport-headers")

    assert response.status_code == 400
    assert response.headers["content-length"] == str(len(response.content))
    assert response.headers["content-type"].startswith("application/json")


def test_application_headers_still_pass_through_alongside_a_forged_transport_header() -> None:
    """The deny-set is narrow: only transport headers are stripped, everything else
    (here Retry-After, alongside the forged Content-Length/Content-Type) survives."""
    response = _client().get("/forged-transport-headers")

    assert response.headers["retry-after"] == "5"
