"""
Standard exception classes for ThinkRealty microservices.

All services should use these as base classes for API exceptions.
Service-specific exceptions should inherit from these shared classes.

Error code convention: {SERVICE_PREFIX}_{CATEGORY}_{NUMBER}
  e.g., LISTING_VALIDATION_001, CMS_NOT_FOUND_002, HR_AUTH_001

Usage:
    from tr_shared.exceptions import (
        BaseAPIException, ValidationError, NotFoundError, ...
    )

Subclass contract:
    Every subclass MUST call ``super().__init__(status_code, error, detail, code)``
    so that the four public attributes (``status_code``, ``error``,
    ``detail_message``, ``error_code``) are set. A subclass that skips the
    super call raises ``TypeError`` at construction time — the bad subclass
    fails loudly instead of rendering a broken error response in production.
"""

from fastapi import HTTPException

_REQUIRED_ATTRS: tuple[str, ...] = ("status_code", "error", "detail_message", "error_code")


class BaseAPIException(HTTPException):
    """Base exception for all API errors.

    Provides standard structure with HTTP status code, error message,
    optional detail, and service-specific error code.

    Args:
        status_code: HTTP status code
        error: Human-readable error message
        detail: Detailed error description (optional)
        code: Error code in SERVICE_CATEGORY_NUMBER format (optional)
    """

    def __init__(
        self,
        status_code: int,
        error: str,
        detail: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=error)
        self.error = error
        self.detail_message = detail
        self.error_code = code

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Wrap subclass ``__init__`` to enforce the attribute contract.

        After the subclass constructor runs, every required attribute must
        exist on the instance. Missing attrs => ``TypeError`` — catches
        subclasses that forget ``super().__init__(...)`` before the broken
        exception leaks into a FastAPI handler.
        """
        super().__init_subclass__(**kwargs)
        original_init = cls.__init__

        def _verified_init(self: "BaseAPIException", *args: object, **kw: object) -> None:
            original_init(self, *args, **kw)
            missing = [a for a in _REQUIRED_ATTRS if not hasattr(self, a)]
            if missing:
                raise TypeError(
                    f"{type(self).__name__} did not set required attributes "
                    f"{missing}. Every BaseAPIException subclass must call "
                    "super().__init__(status_code=..., error=..., detail=..., "
                    "code=...). See tr_shared.exceptions docstring.",
                )

        cls.__init__ = _verified_init  # type: ignore[method-assign]

    def to_dict(self) -> dict:
        """Serialize to the standard error response shape.

        Useful in custom exception handlers that need to build the JSON body::

            @app.exception_handler(BaseAPIException)
            async def handle(request, exc):
                return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
        """
        body: dict = {"error": self.error}
        if self.detail_message:
            body["detail"] = self.detail_message
        if self.error_code:
            body["code"] = self.error_code
        return body


# ---------------------------------------------------------------------------
# Client Errors (4xx)
# ---------------------------------------------------------------------------


class ValidationError(BaseAPIException):
    """Request validation failed (400)."""

    def __init__(self, detail: str, code: str = "VALIDATION_001") -> None:
        super().__init__(status_code=400, error="Validation failed", detail=detail, code=code)


class AuthenticationError(BaseAPIException):
    """Authentication required or failed (401)."""

    def __init__(self, detail: str = "Authentication required", code: str = "AUTH_001") -> None:
        super().__init__(status_code=401, error="Authentication failed", detail=detail, code=code)


class AuthorizationError(BaseAPIException):
    """Permission denied (403)."""

    def __init__(self, detail: str = "Operation not permitted", code: str = "FORBIDDEN_001") -> None:
        super().__init__(status_code=403, error="Authorization failed", detail=detail, code=code)


class NotFoundError(BaseAPIException):
    """Resource not found (404)."""

    def __init__(
        self,
        resource: str = "Resource",
        identifier: str | None = None,
        code: str = "NOT_FOUND_001",
    ) -> None:
        detail = f"{resource} not found" if not identifier else f"{resource} {identifier} not found"
        super().__init__(status_code=404, error=f"{resource} not found", detail=detail, code=code)


class ConflictError(BaseAPIException):
    """Resource conflict (409)."""

    def __init__(self, detail: str = "Resource conflict", code: str = "CONFLICT_001") -> None:
        super().__init__(status_code=409, error="Conflict", detail=detail, code=code)


class RateLimitError(BaseAPIException):
    """Rate limit exceeded (429)."""

    def __init__(self, detail: str = "Rate limit exceeded", code: str = "RATE_LIMIT_001") -> None:
        super().__init__(status_code=429, error="Rate limit exceeded", detail=detail, code=code)


# ---------------------------------------------------------------------------
# Server Errors (5xx)
# ---------------------------------------------------------------------------


class DatabaseError(BaseAPIException):
    """Database operation failed (500)."""

    def __init__(self, detail: str = "Database error", code: str = "DATABASE_001") -> None:
        super().__init__(status_code=500, error="Database error", detail=detail, code=code)


class InternalServerError(BaseAPIException):
    """Unhandled internal error (500)."""

    def __init__(self, detail: str = "Internal server error", code: str = "INTERNAL_001") -> None:
        super().__init__(status_code=500, error="Internal server error", detail=detail, code=code)


class ServiceUnavailableError(BaseAPIException):
    """Downstream service unavailable (503)."""

    def __init__(self, detail: str = "Service unavailable", code: str = "SERVICE_UNAVAILABLE_001") -> None:
        super().__init__(status_code=503, error="Service unavailable", detail=detail, code=code)


class ServiceTimeoutError(BaseAPIException):
    """Downstream service timeout (504)."""

    def __init__(self, detail: str = "Service timeout", code: str = "SERVICE_TIMEOUT_001") -> None:
        super().__init__(status_code=504, error="Service timeout", detail=detail, code=code)


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "BaseAPIException",
    "ConflictError",
    "DatabaseError",
    "InternalServerError",
    "NotFoundError",
    "RateLimitError",
    "ServiceTimeoutError",
    "ServiceUnavailableError",
    "ValidationError",
]
