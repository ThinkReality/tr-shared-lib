from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.events import DurableEventPublisher

pytestmark = pytest.mark.integration

TENANT_ID = "00000000-0000-0000-0000-000000000001"
ACTOR_ID = "11111111-1111-1111-1111-111111111111"


def _outbox_ddl(schema: str, table: str) -> str:
    return f"""
        CREATE TABLE {schema}.{table} (
            id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            event_type text NOT NULL,
            tenant_id uuid NOT NULL,
            actor_id uuid,
            data jsonb NOT NULL,
            metadata jsonb DEFAULT '{{}}'::jsonb NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            published_at timestamp with time zone
        )
    """


@pytest_asyncio.fixture
async def outbox(postgres_dsn: str):
    engine = create_async_engine(postgres_dsn, poolclass=NullPool)
    schema = f"outbox_{uuid.uuid4().hex[:8]}"
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await conn.execute(text(_outbox_ddl(schema, "undelivered_events")))
        await conn.execute(text(_outbox_ddl(schema, "outbox_v2")))
    try:
        yield engine, schema
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await engine.dispose()


async def _rows(engine, schema: str, table: str = "undelivered_events") -> list[dict]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                f"SELECT id, event_type, tenant_id, actor_id, data, metadata FROM {schema}.{table}"
            )
        )
        return [dict(row) for row in result.mappings().all()]


async def test_a_committed_event_is_stored_as_published(outbox):
    engine, schema = outbox
    async with async_sessionmaker(engine)() as session, session.begin():
        event_id = await DurableEventPublisher(session=session, schema=schema).publish(
            event_type="admin.integration.platform.created",
            tenant_id=TENANT_ID,
            data={"platform_name": "PropertyFinder API"},
            actor_id=ACTOR_ID,
        )

    (row,) = await _rows(engine, schema)
    assert row["id"] == event_id
    assert row["event_type"] == "admin.integration.platform.created"
    assert str(row["tenant_id"]) == TENANT_ID
    assert str(row["actor_id"]) == ACTOR_ID
    assert row["data"] == {"platform_name": "PropertyFinder API"}


async def test_the_stored_metadata_is_empty_when_the_caller_gives_none(outbox):
    engine, schema = outbox
    async with async_sessionmaker(engine)() as session, session.begin():
        await DurableEventPublisher(session=session, schema=schema).publish(
            event_type="admin.x", tenant_id=TENANT_ID, data={}
        )

    (row,) = await _rows(engine, schema)
    assert row["metadata"] == {}


async def test_the_stored_metadata_is_exactly_the_callers(outbox):
    engine, schema = outbox
    async with async_sessionmaker(engine)() as session, session.begin():
        await DurableEventPublisher(session=session, schema=schema).publish(
            event_type="admin.x",
            tenant_id=TENANT_ID,
            data={},
            metadata={"correlation_id": "cid-1"},
        )

    (row,) = await _rows(engine, schema)
    assert row["metadata"] == {"correlation_id": "cid-1"}


async def test_a_rolled_back_transaction_leaves_no_event(outbox):
    engine, schema = outbox
    async with async_sessionmaker(engine)() as session:
        await session.begin()
        await DurableEventPublisher(session=session, schema=schema).publish(
            event_type="admin.x", tenant_id=TENANT_ID, data={}
        )
        await session.rollback()

    assert await _rows(engine, schema) == []


async def test_publishing_outside_a_transaction_is_refused_and_writes_nothing(outbox):
    engine, schema = outbox
    async with async_sessionmaker(engine)() as session:
        with pytest.raises(RuntimeError, match="open SQLAlchemy transaction"):
            await DurableEventPublisher(session=session, schema=schema).publish(
                event_type="admin.x", tenant_id=TENANT_ID, data={}
            )

    assert await _rows(engine, schema) == []


async def test_a_custom_table_name_receives_the_event(outbox):
    engine, schema = outbox
    async with async_sessionmaker(engine)() as session, session.begin():
        await DurableEventPublisher(session=session, schema=schema, table_name="outbox_v2").publish(
            event_type="admin.x", tenant_id=TENANT_ID, data={}
        )

    assert len(await _rows(engine, schema, "outbox_v2")) == 1
    assert await _rows(engine, schema) == []
