"""G6d — the guard fires only when eager mode AND an open transaction on a
tracked session actually coincide at dispatch time, not on static shape."""

from __future__ import annotations

import pytest
from celery import Celery

from tr_shared.testing.transaction_guard import install_transaction_guard, track_session


class _FakeSession:
    def __init__(self, *, open_transaction: bool) -> None:
        self._open = open_transaction

    def in_transaction(self) -> bool:
        return self._open


@pytest.fixture
def eager_app() -> Celery:
    app = Celery("g6d-test", broker="memory://", backend="cache+memory://")
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
    install_transaction_guard(app)

    @app.task(name="g6d_test.noop")
    def noop() -> str:
        return "ran"

    app.noop = noop  # type: ignore[attr-defined]
    yield app
    app.conf.task_always_eager = False


def test_fires_when_dispatched_inside_open_transaction(eager_app: Celery) -> None:
    session = _FakeSession(open_transaction=True)
    with pytest.raises(AssertionError, match="open, uncommitted transaction"):
        with track_session(session):
            eager_app.noop.delay()  # type: ignore[attr-defined]


def test_silent_when_transaction_already_closed(eager_app: Celery) -> None:
    session = _FakeSession(open_transaction=False)
    with track_session(session):
        result = eager_app.noop.delay()  # type: ignore[attr-defined]
    assert result.get() == "ran"


def test_silent_when_no_session_is_tracked(eager_app: Celery) -> None:
    result = eager_app.noop.delay()  # type: ignore[attr-defined]
    assert result.get() == "ran"


def test_silent_when_not_in_eager_mode() -> None:
    app = Celery("g6d-test-noneager", broker="memory://", backend="cache+memory://")
    install_transaction_guard(app)

    @app.task(name="g6d_test.noop2")
    def noop() -> str:
        return "ran"

    session = _FakeSession(open_transaction=True)
    # Not eager: .delay() would try to actually publish to the broker, which we
    # don't want in a unit test — just prove the guard's own eager-mode gate by
    # calling the tracer entrypoint the signal handler itself would receive.
    from tr_shared.testing.transaction_guard import _check_no_open_transaction

    with track_session(session):
        _check_no_open_transaction(task=noop)  # must not raise — app is not eager
