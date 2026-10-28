import pytest

from tr_shared.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BaseAPIException,
    ConflictError,
    ContentTooLargeError,
    DatabaseError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)


class TestBaseAPIException:
    def test_status_code(self):
        exc = BaseAPIException(status_code=400, error="Bad request")
        assert exc.status_code == 400

    def test_error_attribute(self):
        exc = BaseAPIException(status_code=400, error="Bad request")
        assert exc.error == "Bad request"

    def test_detail_message(self):
        exc = BaseAPIException(status_code=400, error="Bad", detail="more info", code="X_001")
        assert exc.detail_message == "more info"
        assert exc.error_code == "X_001"


class TestClientErrors:
    def test_validation_error(self):
        exc = ValidationError("field is required")
        assert exc.status_code == 400

    def test_authentication_error(self):
        exc = AuthenticationError()
        assert exc.status_code == 401

    def test_authorization_error(self):
        exc = AuthorizationError()
        assert exc.status_code == 403

    def test_not_found_error_default(self):
        exc = NotFoundError()
        assert exc.status_code == 404
        assert "Resource" in exc.error

    def test_not_found_error_with_identifier(self):
        exc = NotFoundError(resource="Lead", identifier="abc-123")
        assert "abc-123" in exc.detail_message

    def test_conflict_error(self):
        exc = ConflictError()
        assert exc.status_code == 409

    def test_content_too_large_error(self):
        exc = ContentTooLargeError()
        assert exc.status_code == 413

    def test_rate_limit_error(self):
        exc = RateLimitError()
        assert exc.status_code == 429

    def test_rate_limit_error_keeps_extra_headers_beside_retry_after(self):
        exc = RateLimitError(retry_after=7, headers={"X-RateLimit-Limit": "5"})
        assert exc.headers == {"X-RateLimit-Limit": "5", "Retry-After": "7"}


class TestServerErrors:
    def test_database_error(self):
        exc = DatabaseError()
        assert exc.status_code == 500

    def test_internal_server_error(self):
        exc = InternalServerError()
        assert exc.status_code == 500

    def test_service_unavailable_error(self):
        exc = ServiceUnavailableError()
        assert exc.status_code == 503

    def test_service_unavailable_carries_retry_after(self):
        assert ServiceUnavailableError(retry_after=3).headers == {"Retry-After": "3"}

    def test_service_unavailable_without_retry_after_sets_no_header(self):
        assert ServiceUnavailableError().headers is None

    def test_service_timeout_error(self):
        exc = ServiceTimeoutError()
        assert exc.status_code == 504


_REQUIRED_ATTRS = ("status_code", "error", "detail_message", "error_code")
_ALL_BUILTIN_EXC = (
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ConflictError,
    ContentTooLargeError,
    RateLimitError,
    DatabaseError,
    InternalServerError,
    ServiceUnavailableError,
    ServiceTimeoutError,
)


def _construct(cls):
    if cls is ValidationError:
        return cls(detail="validation failed")
    return cls()


class TestSubclassContract:
    @pytest.mark.parametrize("cls", _ALL_BUILTIN_EXC)
    def test_all_builtin_subclasses_set_required_attrs(self, cls):
        exc = _construct(cls)
        for attr in _REQUIRED_ATTRS:
            assert hasattr(exc, attr), f"{cls.__name__} missing {attr}"

    def test_subclass_skipping_super_raises_type_error(self):
        class BrokenExc(BaseAPIException):
            def __init__(self) -> None:  # noqa: D401 — intentional bug
                pass

        with pytest.raises(TypeError, match="did not set required attributes"):
            BrokenExc()

    def test_subclass_calling_super_passes(self):
        class GoodExc(BaseAPIException):
            def __init__(self) -> None:
                super().__init__(status_code=418, error="teapot")

        exc = GoodExc()
        assert exc.status_code == 418
        assert exc.error == "teapot"
