# Error code format: {SERVICE_PREFIX}_{CATEGORY}_{NUMBER}
# e.g. LISTING_VALIDATION_001, CMS_NOT_FOUND_002

from fastapi import HTTPException

_REQUIRED_ATTRS: tuple[str, ...] = ("status_code", "error", "detail_message", "error_code")


class BaseAPIException(HTTPException):

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
        # Wraps __init__ to TypeError-fail loudly when super().__init__ is skipped.
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
        """Returns ``{"error": {"message", "code"?, "detail"?}}``."""
        from tr_shared.schemas.error_envelope import build_error_envelope

        return build_error_envelope(
            message=self.error,
            code=self.error_code,
            detail=self.detail_message,
        )


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
    """Rate limit exceeded (429). Handler must surface ``self.headers`` to emit ``Retry-After``."""

    def __init__(
        self,
        detail: str = "Rate limit exceeded",
        code: str = "RATE_LIMIT_001",
        retry_after: int | None = None,
    ) -> None:
        super().__init__(status_code=429, error="Rate limit exceeded", detail=detail, code=code)
        if retry_after is not None:
            self.headers = {"Retry-After": str(retry_after)}


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
