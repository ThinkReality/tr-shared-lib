import pytest
import structlog

from tr_shared.http.correlation import correlation_headers


@pytest.fixture(autouse=True)
def _clean_context():
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def test_the_bound_id_becomes_the_outbound_header():
    structlog.contextvars.bind_contextvars(correlation_id="corr-1")

    assert correlation_headers() == {"X-Correlation-ID": "corr-1"}


def test_nothing_bound_sends_no_header_at_all():
    assert correlation_headers() == {}


def test_an_empty_bound_id_is_not_sent():
    structlog.contextvars.bind_contextvars(correlation_id="")

    assert correlation_headers() == {}


def test_the_id_is_read_at_call_time_not_captured_earlier():
    structlog.contextvars.bind_contextvars(correlation_id="first")
    first = correlation_headers()
    structlog.contextvars.bind_contextvars(correlation_id="second")

    assert first == {"X-Correlation-ID": "first"}
    assert correlation_headers() == {"X-Correlation-ID": "second"}
