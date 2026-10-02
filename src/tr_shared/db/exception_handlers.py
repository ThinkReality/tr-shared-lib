from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from tr_shared.contracts.availability import UNAVAILABLE_RETRY_AFTER_SECONDS, DatabaseOutageCode
from tr_shared.db.errors import DatabaseTimeoutError, DatabaseUnavailableError
from tr_shared.exceptions import ServiceTimeoutError, ServiceUnavailableError
from tr_shared.middleware.exception_handlers import base_api_exception_handler


async def _unavailable(request: Request, detail: str, code: DatabaseOutageCode) -> JSONResponse:
    return await base_api_exception_handler(
        request,
        ServiceUnavailableError(
            detail=detail, code=code, retry_after=UNAVAILABLE_RETRY_AFTER_SECONDS
        ),
    )


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return await _unavailable(
        request, "Database unavailable", cast(DatabaseUnavailableError, exc).code
    )


async def _pool_exhausted(request: Request, exc: Exception) -> JSONResponse:
    return await _unavailable(
        request, "Database connection pool exhausted", DatabaseOutageCode.POOL_EXHAUSTED
    )


async def _statement_timeout(request: Request, exc: Exception) -> JSONResponse:
    return await base_api_exception_handler(
        request,
        ServiceTimeoutError(
            detail="Database statement timed out", code=DatabaseOutageCode.STATEMENT_TIMEOUT
        ),
    )


def register_db_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DatabaseUnavailableError, _database_unavailable)
    app.add_exception_handler(PoolTimeoutError, _pool_exhausted)
    app.add_exception_handler(DatabaseTimeoutError, _statement_timeout)
