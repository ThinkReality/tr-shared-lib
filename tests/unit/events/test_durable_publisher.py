"""Tests for tr_shared.events.DurableEventPublisher."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tr_shared.events import DurableEventPublisher


def _make_session(*, in_txn: bool = True) -> AsyncMock:
    session = AsyncMock()
    session.in_transaction = MagicMock(return_value=in_txn)
    return session


class TestDurableEventPublisher:
    async def test_insert_uses_caller_session(self):
        session = _make_session(in_txn=True)
        publisher = DurableEventPublisher(
            session=session, schema="admin", source_service="admin-panel",
        )
        rid = await publisher.publish(
            event_type="admin.integration.platform.created",
            tenant_id="00000000-0000-0000-0000-000000000001",
            data={"platform_name": "PropertyFinder API", "webhook_token": "wh_abc"},
            actor_id="11111111-1111-1111-1111-111111111111",
        )
        session.execute.assert_awaited_once()
        # Returns a UUID
        assert str(rid)
        call_args = session.execute.call_args
        stmt = str(call_args[0][0])
        params = call_args[0][1]
        assert "INSERT INTO admin.undelivered_events" in stmt
        assert params["event_type"] == "admin.integration.platform.created"
        assert params["tenant_id"] == "00000000-0000-0000-0000-000000000001"
        assert params["actor_id"] == "11111111-1111-1111-1111-111111111111"
        assert json.loads(params["data"]) == {
            "platform_name": "PropertyFinder API",
            "webhook_token": "wh_abc",
        }

    async def test_source_service_injected_into_metadata(self):
        session = _make_session(in_txn=True)
        publisher = DurableEventPublisher(
            session=session, schema="admin", source_service="admin-panel",
        )
        await publisher.publish(
            event_type="admin.x", tenant_id="t", data={},
        )
        params = session.execute.call_args[0][1]
        metadata = json.loads(params["metadata"])
        assert metadata["source_service"] == "admin-panel"

    async def test_caller_metadata_merged(self):
        session = _make_session(in_txn=True)
        publisher = DurableEventPublisher(
            session=session, schema="admin", source_service="admin-panel",
        )
        await publisher.publish(
            event_type="admin.x",
            tenant_id="t",
            data={},
            metadata={"correlation_id": "cid-1"},
        )
        params = session.execute.call_args[0][1]
        metadata = json.loads(params["metadata"])
        assert metadata["correlation_id"] == "cid-1"
        assert metadata["source_service"] == "admin-panel"

    async def test_raises_when_no_transaction(self):
        session = _make_session(in_txn=False)
        publisher = DurableEventPublisher(
            session=session, schema="admin", source_service="admin-panel",
        )
        with pytest.raises(RuntimeError, match="open SQLAlchemy transaction"):
            await publisher.publish(
                event_type="admin.x", tenant_id="t", data={},
            )
        session.execute.assert_not_called()

    async def test_custom_table_name(self):
        session = _make_session(in_txn=True)
        publisher = DurableEventPublisher(
            session=session,
            schema="admin",
            source_service="admin-panel",
            table_name="outbox_v2",
        )
        await publisher.publish(
            event_type="x", tenant_id="t", data={},
        )
        stmt = str(session.execute.call_args[0][0])
        assert "INSERT INTO admin.outbox_v2" in stmt
