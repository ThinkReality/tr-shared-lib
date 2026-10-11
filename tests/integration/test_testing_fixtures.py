import pytest
from sqlalchemy import text

from tr_shared.contracts import DatabaseOutageCode
from tr_shared.db import DatabaseTimeoutError, DatabaseUnavailableError
from tr_shared.testing.isolation import savepoint_session

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def tr_database_url(postgres_dsn: str) -> str:
    return postgres_dsn


def _raise_sqlstate(sqlstate: str) -> str:
    return f"DO $$ BEGIN RAISE EXCEPTION 'relayed' USING ERRCODE = '{sqlstate}'; END $$"


async def test_a_lost_connection_through_tr_session_is_unavailable(tr_session):
    with pytest.raises(DatabaseUnavailableError) as caught:
        await tr_session.execute(text(_raise_sqlstate("08006")))

    assert caught.value.code is DatabaseOutageCode.CONNECTION_LOST


async def test_a_cancelled_statement_through_tr_session_is_a_timeout(tr_session):
    with pytest.raises(DatabaseTimeoutError):
        await tr_session.execute(text(_raise_sqlstate("57014")))


async def test_a_lost_connection_leaves_tr_engine_usable(tr_engine):
    with pytest.raises(DatabaseUnavailableError):
        async with savepoint_session(tr_engine) as session:
            await session.execute(text(_raise_sqlstate("08006")))

    async with savepoint_session(tr_engine) as session:
        assert await session.scalar(text("SELECT 1")) == 1
