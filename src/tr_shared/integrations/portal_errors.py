"""Generic portal-integration error taxonomy.

Portal adapters (PropertyFinder, Bayut/Dubizzle, and any future portal — e.g. holiday-home portals)
raise these instead of portal-specific exceptions. Each extends the matching ``tr_shared.exceptions``
base so the standard error handler + HTTP status mapping work unchanged.

The Celery retry policy keys on the **retryable** subclasses::

    autoretry_for = (PortalServerError, PortalRateLimitError, PortalUnavailableError)

Portal-specific clients may subclass these to carry extra context, but the generic bases are enough for
routing + retry decisions. ``portal`` (a portal name string) is carried on every error for logging.
"""

from tr_shared.exceptions import (
    AuthenticationError,
    BaseAPIException,
    ConflictError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)


class PortalError(BaseAPIException):
    """Generic portal-integration failure (502)."""

    def __init__(
        self,
        detail: str = "Portal integration error",
        code: str = "PORTAL_ERROR_001",
        *,
        portal: str | None = None,
    ) -> None:
        super().__init__(status_code=502, error="Portal integration error", detail=detail, code=code)
        self.portal = portal


class PortalAuthError(AuthenticationError):
    """Portal authentication/token failure (401)."""

    def __init__(
        self,
        detail: str = "Portal authentication failed",
        code: str = "PORTAL_AUTH_001",
        *,
        portal: str | None = None,
    ) -> None:
        super().__init__(detail=detail, code=code)
        self.portal = portal


class PortalValidationError(ValidationError):
    """Portal rejected the payload (4xx, not retryable)."""

    def __init__(
        self,
        detail: str = "Portal validation failed",
        code: str = "PORTAL_VALIDATION_001",
        *,
        portal: str | None = None,
        errors: list[dict] | None = None,
    ) -> None:
        super().__init__(detail=detail, code=code)
        self.portal = portal
        self.errors = errors or []


class PortalRateLimitError(RateLimitError):
    """Portal rate limit hit (429, retryable)."""

    def __init__(
        self,
        detail: str = "Portal rate limit exceeded",
        code: str = "PORTAL_RATE_LIMIT_001",
        *,
        portal: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(detail=detail, code=code)
        self.portal = portal
        self.retry_after = retry_after


class PortalDuplicateError(ConflictError):
    """Listing already exists on the portal (409). Carries the existing id for linking."""

    def __init__(
        self,
        detail: str = "Listing already exists on portal",
        code: str = "PORTAL_DUPLICATE_001",
        *,
        portal: str | None = None,
        existing_listing_id: str | None = None,
        reference: str | None = None,
    ) -> None:
        super().__init__(detail=detail, code=code)
        self.portal = portal
        self.existing_listing_id = existing_listing_id
        self.reference = reference


class PortalNotFoundError(NotFoundError):
    """Portal resource not found (404)."""

    def __init__(
        self,
        resource: str = "Portal resource",
        identifier: str | None = None,
        code: str = "PORTAL_NOT_FOUND_001",
        *,
        portal: str | None = None,
    ) -> None:
        super().__init__(resource=resource, identifier=identifier, code=code)
        self.portal = portal


class PortalUnavailableError(ServiceUnavailableError):
    """Portal API unavailable (503, retryable)."""

    def __init__(
        self,
        detail: str = "Portal unavailable",
        code: str = "PORTAL_UNAVAILABLE_001",
        *,
        portal: str | None = None,
    ) -> None:
        super().__init__(detail=detail, code=code)
        self.portal = portal


class PortalServerError(InternalServerError):
    """Portal returned a 5xx (retryable)."""

    def __init__(
        self,
        detail: str = "Portal server error",
        code: str = "PORTAL_SERVER_001",
        *,
        portal: str | None = None,
    ) -> None:
        super().__init__(detail=detail, code=code)
        self.portal = portal
