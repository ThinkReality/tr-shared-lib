# No bare Exception handler here — GlobalErrorHandlerMiddleware owns 500s (Slack + correlation).

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from tr_shared.exceptions import BaseAPIException
from tr_shared.schemas.error_envelope import build_error_envelope


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


async def base_api_exception_handler(request: Request, exc: BaseAPIException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_envelope(
            message=exc.error,
            code=exc.error_code,
            correlation_id=_correlation_id(request),
            detail=exc.detail_message,
        ),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_envelope(
            message=str(exc.detail),
            code=f"HTTP_{exc.status_code}",
            correlation_id=_correlation_id(request),
        ),
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
            fields=exc.errors(),
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BaseAPIException, base_api_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
