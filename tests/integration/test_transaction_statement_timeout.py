import pytest
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.orm import Session

from tr_shared.db import DatabaseTimeoutError, OutageTypedQueuePool, prepare_sync_engine
from tr_shared.db.session import _QUERY_CANCELED_SQLSTATE, _sqlstate

pytestmark = pytest.mark.integration

_SHORT_CAP = 1.0
_OVER_THE_CAP = {"s": _SHORT_CAP * 3}
_SLEEP = text("SELECT pg_sleep(:s)")
_CURRENT_CAP_MS = "SELECT setting FROM pg_settings WHERE name = 'statement_timeout'"


def _capped_engine(sync_dsn: URL) -> Engine:
    engine = create_engine(sync_dsn, poolclass=OutageTypedQueuePool)
    prepare_sync_engine(engine, service_name="cap-test", statement_timeout_seconds=_SHORT_CAP)
    return engine


def test_every_transaction_on_a_connection_is_capped(sync_dsn):
    engine = _capped_engine(sync_dsn)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
            conn.commit()
            with pytest.raises(DatabaseTimeoutError) as caught:
                conn.execute(_SLEEP, _OVER_THE_CAP)
    finally:
        engine.dispose()
    assert _sqlstate(caught.value.__cause__) == _QUERY_CANCELED_SQLSTATE


def test_an_orm_session_is_capped(sync_dsn):
    engine = _capped_engine(sync_dsn)
    try:
        with Session(engine) as session, pytest.raises(DatabaseTimeoutError) as caught:
            session.execute(_SLEEP, _OVER_THE_CAP)
    finally:
        engine.dispose()
    assert _sqlstate(caught.value.__cause__) == _QUERY_CANCELED_SQLSTATE


def test_the_cap_ends_with_its_transaction(sync_dsn):
    engine = _capped_engine(sync_dsn)
    try:
        with engine.connect() as conn:
            inside = conn.exec_driver_sql(_CURRENT_CAP_MS).scalar_one()
            conn.commit()
            with conn.connection.dbapi_connection.cursor() as cursor:
                cursor.execute(_CURRENT_CAP_MS)
                after = cursor.fetchone()[0]
    finally:
        engine.dispose()
    assert int(inside) == int(_SHORT_CAP * 1000)
    assert after != inside
