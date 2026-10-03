import logging
import time
import uuid

import pytest
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from tests.integration.test_db_error_translation import _raise_sqlstate
from tr_shared.contracts import DatabaseOutageCode
from tr_shared.contracts.db_pool import (
    DB_CONNECT_TIMEOUT_SECONDS,
    DB_STATEMENT_TIMEOUT_SECONDS,
    StatementTimeoutProfile,
)
from tr_shared.db import (
    DatabaseTimeoutError,
    DatabaseUnavailableError,
    OutageTypedQueuePool,
    prepare_sync_engine,
)
from tr_shared.db.session import _QUERY_CANCELED_SQLSTATE, _sqlstate

pytestmark = pytest.mark.integration

_REQUEST_CAP = DB_STATEMENT_TIMEOUT_SECONDS[StatementTimeoutProfile.REQUEST]
_SHORT_CAP = 1.0
_SLACK_SECONDS = 2
_FAILED_CONNECTS = 3


def _engine(
    url: URL,
    *,
    statement_timeout_seconds: float = _REQUEST_CAP,
    poolclass: type = OutageTypedQueuePool,
    **engine_kwargs,
) -> Engine:
    engine = create_engine(
        url,
        poolclass=poolclass,
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS},
        **engine_kwargs,
    )
    prepare_sync_engine(
        engine, service_name="sync-test", statement_timeout_seconds=statement_timeout_seconds
    )
    return engine


def _unreachable(driver: str, host: str, port: int) -> URL:
    return URL.create(driver, username="u", password="p", host=host, port=port, database="db")


def _connect_once(engine: Engine) -> None:
    try:
        with engine.connect():
            pass
    finally:
        engine.dispose()


@pytest.mark.parametrize("poolclass", [OutageTypedQueuePool, NullPool])
def test_a_refused_connect_is_unavailable(sync_driver, poolclass):
    with pytest.raises(DatabaseUnavailableError) as caught:
        _connect_once(_engine(_unreachable(sync_driver, "127.0.0.1", 1), poolclass=poolclass))
    assert caught.value.code is DatabaseOutageCode.CONNECT_FAILED
    assert "Connection refused" in str(caught.value.__cause__)


def test_an_unresolvable_host_is_unavailable(sync_driver):
    with pytest.raises(DatabaseUnavailableError) as caught:
        _connect_once(_engine(_unreachable(sync_driver, "nonexistent-host.invalid", 5432)))
    assert caught.value.code is DatabaseOutageCode.CONNECT_FAILED
    assert "nonexistent-host.invalid" in str(caught.value.__cause__)


def test_a_blackholed_connect_gives_up_at_the_contract_budget(sync_driver):
    started = time.monotonic()
    with pytest.raises(DatabaseUnavailableError) as caught:
        _connect_once(_engine(_unreachable(sync_driver, "10.255.255.1", 5432)))
    assert caught.value.code is DatabaseOutageCode.CONNECT_FAILED
    assert "timeout expired" in str(caught.value.__cause__)
    assert time.monotonic() - started < DB_CONNECT_TIMEOUT_SECONDS + _SLACK_SECONDS


def test_a_sync_wrong_password_is_an_outage(sync_dsn):
    with pytest.raises(DatabaseUnavailableError) as caught:
        _connect_once(_engine(sync_dsn.set(password="wrong")))
    assert caught.value.code is DatabaseOutageCode.CONNECT_FAILED
    assert "password authentication failed" in str(caught.value.__cause__)
    assert _sqlstate(caught.value.__cause__) is None


def test_a_role_over_its_connection_limit_is_unavailable_until_the_limit_lifts(
    sync_dsn, sync_admin
):
    role = f"tr_capped_{uuid.uuid4().hex[:8]}"
    with sync_admin.connect() as conn:
        conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'capped' CONNECTION LIMIT 0"))
    engine = _engine(
        sync_dsn.set(username=role, password="capped"),
        pool_size=1,
        max_overflow=0,
        pool_timeout=_SHORT_CAP,
    )
    try:
        failures = []
        for _ in range(_FAILED_CONNECTS):
            with pytest.raises(DatabaseUnavailableError) as caught, engine.connect():
                pass
            failures.append((caught.value.code, str(caught.value.__cause__)))
        with sync_admin.connect() as conn:
            conn.execute(text(f"ALTER ROLE {role} CONNECTION LIMIT -1"))
        with engine.connect() as conn:
            recovered = conn.scalar(text("SELECT current_user"))
    finally:
        engine.dispose()
        with sync_admin.connect() as conn:
            conn.execute(text(f"DROP ROLE {role}"))
    assert [code for code, _ in failures] == [DatabaseOutageCode.CONNECT_FAILED] * _FAILED_CONNECTS
    assert all("too many connections for role" in cause for _, cause in failures)
    assert recovered == role


def test_a_statement_over_its_cap_is_typed_and_logged(sync_dsn, caplog):
    engine = _engine(sync_dsn, statement_timeout_seconds=_SHORT_CAP)
    try:
        with caplog.at_level(logging.WARNING, logger="tr_shared.db.session"):
            with pytest.raises(DatabaseTimeoutError) as caught, Session(engine) as session:
                session.execute(text("SELECT pg_sleep(:s)"), {"s": _SHORT_CAP * 3})
    finally:
        engine.dispose()
    assert _sqlstate(caught.value.__cause__) == _QUERY_CANCELED_SQLSTATE
    [record] = [r for r in caplog.records if r.getMessage() == "db_statement_timeout"]
    assert "pg_sleep" in record.statement
    assert record.statement_timeout_seconds == _SHORT_CAP


def test_a_terminated_backend_is_connection_lost_and_the_next_checkout_recovers(
    sync_dsn, terminate_backend_sync
):
    engine = _engine(sync_dsn, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as conn:
            pid = conn.scalar(text("SELECT pg_backend_pid()"))
            terminate_backend_sync(pid)
            with pytest.raises(DatabaseUnavailableError) as caught:
                conn.execute(text("SELECT 1"))
        with engine.connect() as conn:
            recovered = conn.scalar(text("SELECT pg_backend_pid()"))
    finally:
        engine.dispose()
    assert caught.value.code is DatabaseOutageCode.CONNECTION_LOST
    assert recovered != pid


@pytest.mark.parametrize("sqlstate", ["08006", "57P01", "57P03"])
def test_a_relayed_backend_outage_is_connection_lost(sync_dsn, sqlstate):
    engine = _engine(sync_dsn)
    try:
        with pytest.raises(DatabaseUnavailableError) as caught, engine.connect() as conn:
            conn.execute(text(_raise_sqlstate(sqlstate)))
    finally:
        engine.dispose()
    assert caught.value.code is DatabaseOutageCode.CONNECTION_LOST
    assert _sqlstate(caught.value.__cause__) == sqlstate


def test_an_error_on_a_live_connection_is_not_an_outage(sync_dsn):
    engine = _engine(sync_dsn)
    try:
        with pytest.raises(OperationalError) as caught, engine.connect() as conn:
            conn.execute(text(_raise_sqlstate("53100")))
    finally:
        engine.dispose()
    assert type(caught.value.orig).__name__ == "DiskFull"


def test_a_missing_table_stays_a_programming_error(sync_dsn):
    engine = _engine(sync_dsn)
    try:
        with pytest.raises(ProgrammingError) as caught, engine.connect() as conn:
            conn.execute(text("SELECT * FROM no_such_table"))
    finally:
        engine.dispose()
    assert type(caught.value.orig).__name__ == "UndefinedTable"


def test_pre_ping_still_replaces_a_dead_connection(sync_dsn, terminate_backend_sync):
    engine = _engine(sync_dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            pid = conn.scalar(text("SELECT pg_backend_pid()"))
        terminate_backend_sync(pid)
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT pg_backend_pid()")) != pid
    finally:
        engine.dispose()


def test_an_exhausted_pool_is_unavailable_and_recovers(sync_dsn):
    engine = _engine(sync_dsn, pool_size=1, max_overflow=0, pool_timeout=_SHORT_CAP)
    try:
        with engine.connect() as held:
            held.execute(text("SELECT 1"))
            with pytest.raises(DatabaseUnavailableError) as caught, engine.connect():
                pass
        with engine.connect() as conn:
            recovered = conn.scalar(text("SELECT 1"))
    finally:
        engine.dispose()
    assert caught.value.code is DatabaseOutageCode.POOL_EXHAUSTED
    assert recovered == 1
