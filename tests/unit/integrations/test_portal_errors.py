"""Tests for the generic portal-integration error taxonomy."""

import pytest

from tr_shared.exceptions import (
    AuthenticationError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from tr_shared.integrations import (
    PortalAuthError,
    PortalDuplicateError,
    PortalError,
    PortalNotFoundError,
    PortalRateLimitError,
    PortalServerError,
    PortalUnavailableError,
    PortalValidationError,
)


def test_status_codes_match_their_bases():
    assert PortalError().status_code == 502
    assert PortalAuthError().status_code == 401
    assert PortalValidationError().status_code == 400
    assert PortalRateLimitError().status_code == 429
    assert PortalDuplicateError().status_code == 409
    assert PortalNotFoundError().status_code == 404
    assert PortalUnavailableError().status_code == 503
    assert PortalServerError().status_code == 500


def test_subclass_the_shared_bases():
    assert isinstance(PortalAuthError(), AuthenticationError)
    assert isinstance(PortalValidationError(), ValidationError)
    assert isinstance(PortalRateLimitError(), RateLimitError)
    assert isinstance(PortalDuplicateError(), ConflictError)
    assert isinstance(PortalNotFoundError(), NotFoundError)
    assert isinstance(PortalUnavailableError(), ServiceUnavailableError)
    assert isinstance(PortalServerError(), InternalServerError)


def test_carries_portal_and_extra_context():
    rl = PortalRateLimitError(portal="bayut", retry_after=42)
    assert rl.portal == "bayut"
    assert rl.retry_after == 42

    dup = PortalDuplicateError(portal="propertyfinder", existing_listing_id="pf-99", reference="TR-1")
    assert dup.existing_listing_id == "pf-99"
    assert dup.reference == "TR-1"

    val = PortalValidationError(portal="bayut", errors=[{"field": "price"}])
    assert val.errors == [{"field": "price"}]

    nf = PortalNotFoundError(identifier="loc-1", portal="propertyfinder")
    assert nf.portal == "propertyfinder"


def test_error_code_and_detail_message_set():
    err = PortalServerError("upstream 502", portal="bayut")
    assert err.error_code == "PORTAL_SERVER_001"
    assert err.detail_message == "upstream 502"


def test_retryable_set_distinct_from_terminal():
    retryable = (PortalServerError, PortalRateLimitError, PortalUnavailableError)
    terminal = (PortalValidationError, PortalAuthError, PortalDuplicateError, PortalNotFoundError)
    for exc in retryable:
        assert issubclass(exc, Exception)
    # terminal errors must NOT be subclasses of the retryable ones (so autoretry_for excludes them)
    for t in terminal:
        assert not issubclass(t, retryable)


def test_raisable():
    with pytest.raises(PortalRateLimitError):
        raise PortalRateLimitError(portal="bayut", retry_after=1)
