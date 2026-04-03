"""Tests for tr_shared.exceptions."""

import pytest

from tr_shared.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BaseAPIException,
    ConflictError,
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
        exc = BaseAPIException(
            status_code=400, error="Bad", detail="more info", code="X_001"
        )
        assert exc.detail_message == "more info"
        assert exc.error_code == "X_001"

    def test_to_dict_minimal(self):
        exc = BaseAPIException(status_code=400, error="Bad request")
        d = exc.to_dict()
        assert d == {"error": "Bad request"}

    def test_to_dict_full(self):
        exc = BaseAPIException(
            status_code=400, error="Bad", detail="detail", code="CODE_001"
        )
        d = exc.to_dict()
        assert d == {"error": "Bad", "detail": "detail", "code": "CODE_001"}


class TestClientErrors:
    def test_validation_error(self):
        exc = ValidationError("field is required")
        assert exc.status_code == 400
        assert exc.error_code == "VALIDATION_001"

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

    def test_rate_limit_error(self):
        exc = RateLimitError()
        assert exc.status_code == 429


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

    def test_service_timeout_error(self):
        exc = ServiceTimeoutError()
        assert exc.status_code == 504
