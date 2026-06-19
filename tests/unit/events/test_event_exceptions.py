"""Tests for tr_shared.events.exceptions."""

from tr_shared.events import EventPublishError, EventPublishTransportError


def test_transport_is_subclass_of_base():
    assert issubclass(EventPublishTransportError, EventPublishError)


def test_base_is_plain_exception_not_http():
    # Must NOT inherit the HTTP exception family — this is an internal
    # transport signal, not a request/response error.
    assert issubclass(EventPublishError, Exception)
    assert not issubclass(EventPublishError, ValueError)
    assert not issubclass(EventPublishError, RuntimeError)


def test_transport_error_carries_message():
    exc = EventPublishTransportError("redis down")
    assert str(exc) == "redis down"
    assert isinstance(exc, EventPublishError)
