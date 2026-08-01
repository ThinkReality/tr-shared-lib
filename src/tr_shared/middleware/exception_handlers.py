# No bare Exception handler here — GlobalErrorHandlerMiddleware owns 500s (Slack + correlation).

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from tr_shared.exceptions import BaseAPIException
from tr_shared.schemas.error_envelope import build_error_envelope


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


# Transport-level headers JSONResponse already owns: Content-Length/Content-Type are
# derived from the body it serializes, Transfer-Encoding/Connection are hop-by-hop and
# server-owned. An exception overriding any of these can desync the response from what
# the client is told to expect — e.g. a forged Content-Length larger than the real body
# leaves an HTTP/1.1 client blocked waiting for bytes that never arrive. Only
# application-level headers (Retry-After, WWW-Authenticate, ...) may pass through.
_TRANSPORT_HEADERS = frozenset(
    {"content-length", "content-type", "transfer-encoding", "connection"}
)


def _safe_headers(exc: Exception) -> dict[str, str] | None:
    headers = getattr(exc, "headers", None)
    if not headers:
        return headers
    return {k: v for k, v in headers.items() if k.lower() not in _TRANSPORT_HEADERS}


async def base_api_exception_handler(request: Request, exc: BaseAPIException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_envelope(
            message=exc.error,
            code=exc.error_code,
            correlation_id=_correlation_id(request),
            detail=exc.detail_message,
        ),
        headers=_safe_headers(exc),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_envelope(
            message=str(exc.detail),
            code=f"HTTP_{exc.status_code}",
            correlation_id=_correlation_id(request),
        ),
        headers=_safe_headers(exc),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_error_envelope(
            message="Validation failed",
            code="VALIDATION_ERROR",
            correlation_id=_correlation_id(request),
            # jsonable_encoder coerces non-JSON-serializable entries — notably a
            # field_validator's raised ValueError living in ctx.error — so the 422
            # body serializes instead of crashing into a 500.
            fields=jsonable_encoder(exc.errors()),
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BaseAPIException, base_api_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
