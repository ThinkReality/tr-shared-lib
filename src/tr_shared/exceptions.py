# Error code format: {SERVICE_PREFIX}_{CATEGORY}_{NUMBER}
# e.g. LISTING_VALIDATION_001, CMS_NOT_FOUND_002

from typing import Any, ClassVar

from fastapi import HTTPException

from tr_shared.contracts.headers import HttpHeader

_REQUIRED_ATTRS: tuple[str, ...] = (
    "status_code",
    "error",
    "detail_message",
    "error_code",
    "extra",
)


class BaseAPIException(HTTPException):
    category: ClassVar[str | None] = None

    def __init__(
        self,
        status_code: int,
        error: str,
        detail: str | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=error, headers=headers)
        self.error = error
        self.detail_message = detail
        self.error_code = code
        # Structured detail that belongs INSIDE the canonical `error` object —
        # a per-field validation list, a retry budget, an offending value. It
        # exists because the alternative is what callers did instead: flatten
        # the detail into the message with `"; ".join(...)` and truncate, which
        # is unparseable by the client that has to render it.
        self.extra: dict[str, Any] = extra or {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Wraps __init__ to TypeError-fail loudly when super().__init__ is skipped.
        super().__init_subclass__(**kwargs)
        original_init = cls.__init__

        # `Any`, not `object`: this is a pass-through wrapper around an arbitrary
        # subclass __init__, so mypy must not try to match the forwarded *args
        # against the base signature it happens to see here.
        def _verified_init(self: "BaseAPIException", *args: Any, **kw: Any) -> None:
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


class ValidationError(BaseAPIException):
    """Request validation failed (400)."""

    category = "VALIDATION"

    def __init__(self, detail: str, code: str | None = None) -> None:
        super().__init__(status_code=400, error="Validation failed", detail=detail, code=code)


class AuthenticationError(BaseAPIException):
    """Authentication required or failed (401).

    ``headers`` exists so a 401 can carry its ``WWW-Authenticate`` challenge,
    which RFC 9110 §11.6.1 requires of every 401 response.
    """

    category = "AUTH"

    def __init__(
        self,
        detail: str = "Authentication required",
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=401,
            error="Authentication failed",
            detail=detail,
            code=code,
            headers=headers,
        )


class AuthorizationError(BaseAPIException):
    """Permission denied (403)."""

    category = "FORBIDDEN"

    def __init__(self, detail: str = "Operation not permitted", code: str | None = None) -> None:
        super().__init__(status_code=403, error="Authorization failed", detail=detail, code=code)


class NotFoundError(BaseAPIException):
    """Resource not found (404)."""

    category = "NOT_FOUND"

    def __init__(
        self,
        resource: str = "Resource",
        identifier: str | None = None,
        code: str | None = None,
    ) -> None:
        detail = f"{resource} not found" if not identifier else f"{resource} {identifier} not found"
        super().__init__(status_code=404, error=f"{resource} not found", detail=detail, code=code)


class ConflictError(BaseAPIException):
    """Resource conflict (409)."""

    category = "CONFLICT"

    def __init__(self, detail: str = "Resource conflict", code: str | None = None) -> None:
        super().__init__(status_code=409, error="Conflict", detail=detail, code=code)


class ContentTooLargeError(BaseAPIException):
    """Request content exceeds a size limit or the remaining storage quota (413)."""

    category = "CONTENT_TOO_LARGE"

    def __init__(self, detail: str = "Content too large", code: str | None = None) -> None:
        super().__init__(status_code=413, error="Content too large", detail=detail, code=code)


class RateLimitError(BaseAPIException):
    """Rate limit exceeded (429). Handler must surface ``self.headers`` to emit ``Retry-After``."""

    category = "RATE_LIMIT"

    def __init__(
        self,
        detail: str = "Rate limit exceeded",
        code: str | None = None,
        retry_after: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        merged = dict(headers or {})
        if retry_after is not None:
            merged[HttpHeader.RETRY_AFTER.value] = str(retry_after)
        super().__init__(
            status_code=429,
            error="Rate limit exceeded",
            detail=detail,
            code=code,
            headers=merged or None,
        )


class DatabaseError(BaseAPIException):
    """Database operation failed (500)."""

    category = "DATABASE"

    def __init__(self, detail: str = "Database error", code: str | None = None) -> None:
        super().__init__(status_code=500, error="Database error", detail=detail, code=code)


class InternalServerError(BaseAPIException):
    """Unhandled internal error (500)."""

    category = "INTERNAL"

    def __init__(self, detail: str = "Internal server error", code: str | None = None) -> None:
        super().__init__(status_code=500, error="Internal server error", detail=detail, code=code)


class ServiceUnavailableError(BaseAPIException):
    """Downstream service unavailable (503)."""

    category = "UNAVAILABLE"

    def __init__(
        self,
        detail: str = "Service unavailable",
        code: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(
            status_code=503,
            error="Service unavailable",
            detail=detail,
            code=code,
            headers={HttpHeader.RETRY_AFTER.value: str(retry_after)}
            if retry_after is not None
            else None,
        )


class ServiceTimeoutError(BaseAPIException):
    """Downstream service timeout (504)."""

    category = "TIMEOUT"

    def __init__(self, detail: str = "Service timeout", code: str | None = None) -> None:
        super().__init__(status_code=504, error="Service timeout", detail=detail, code=code)


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "BaseAPIException",
    "ConflictError",
    "ContentTooLargeError",
    "DatabaseError",
    "InternalServerError",
    "NotFoundError",
    "RateLimitError",
    "ServiceTimeoutError",
    "ServiceUnavailableError",
    "ValidationError",
]
