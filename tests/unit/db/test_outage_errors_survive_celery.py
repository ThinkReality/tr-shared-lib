import pickle
import uuid

import pytest
from celery import Celery
from celery.utils.serialization import get_pickleable_exception

from tr_shared.contracts.availability import DatabaseOutageCode
from tr_shared.db.errors import DatabaseTimeoutError, DatabaseUnavailableError

OUTAGES = [
    DatabaseUnavailableError("could not connect", code=DatabaseOutageCode.CONNECT_FAILED),
    DatabaseUnavailableError("connection lost", code=DatabaseOutageCode.CONNECTION_LOST),
    DatabaseUnavailableError("pool exhausted", code=DatabaseOutageCode.POOL_EXHAUSTED),
]


def _stored_failure(exc: Exception) -> BaseException:
    app = Celery("outage-roundtrip", backend="cache+memory://")
    app.conf.update(result_serializer="json", accept_content=["json"])
    task_id = str(uuid.uuid4())
    app.backend.mark_as_failure(task_id, get_pickleable_exception(exc))
    return app.AsyncResult(task_id).result


@pytest.mark.parametrize("exc", OUTAGES, ids=lambda e: e.code.value)
def test_an_outage_keeps_its_class_and_code_through_pickle(exc):
    restored = pickle.loads(pickle.dumps(exc))

    assert type(restored) is DatabaseUnavailableError
    assert restored.code is exc.code
    assert str(restored) == str(exc)


@pytest.mark.parametrize("exc", OUTAGES, ids=lambda e: e.code.value)
def test_the_worker_passes_the_outage_itself_to_failure_handlers(exc):
    assert get_pickleable_exception(exc) is exc


@pytest.mark.parametrize("exc", OUTAGES, ids=lambda e: e.code.value)
def test_a_json_result_backend_returns_the_outage_with_its_code(exc):
    restored = _stored_failure(exc)

    assert type(restored) is DatabaseUnavailableError
    assert restored.code is exc.code
    assert str(restored) == str(exc)


def test_a_statement_timeout_survives_a_json_result_backend():
    restored = _stored_failure(DatabaseTimeoutError("statement exceeded its time cap"))

    assert type(restored) is DatabaseTimeoutError
    assert str(restored) == "statement exceeded its time cap"


def test_the_code_is_still_accepted_by_keyword():
    exc = DatabaseUnavailableError("down", code=DatabaseOutageCode.CONNECT_FAILED)

    assert exc.code is DatabaseOutageCode.CONNECT_FAILED
    assert str(exc) == "down"
