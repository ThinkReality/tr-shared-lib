"""Transactional-outbox event publisher.

Writes the event to ``{schema}.undelivered_events`` inside the caller's
SQLAlchemy transaction, so the event row commits atomically with the
caller's business data. A background drainer publishes rows to Redis
Stream and marks them ``published_at``. Events are never silently lost.

Contract:
- Caller MUST already have an open transaction (``async with session.begin()``).
  Calling ``publish()`` outside a transaction raises ``RuntimeError`` — the
  outbox guarantee is void without txn join.
- Caller owns the commit. The publisher never commits on its own.

Usage::

    publisher = DurableEventPublisher(
        session=self.db,
        schema="admin",
        source_service="admin-panel",
    )
    await publisher.publish(
        event_type=AdminEvents.INTEGRATION_PLATFORM_CREATED,
        tenant_id=str(tenant_id),
        data={...},
        actor_id=str(user_id),
    )
    # Caller commits — event row lands in outbox atomically.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DurableEventPublisher:
    """Writes events to a per-service outbox table via the caller's session.

    Args:
        session: Caller's ``AsyncSession``. Must be inside an open
            transaction when ``publish`` is called.
        schema: Service schema owning the ``undelivered_events`` table
            (e.g. ``"admin"`` for admin-panel).
        source_service: Logical service name, stored on the event row so
            consumers can trace provenance.
        table_name: Override for the outbox table name. Defaults to
            ``"undelivered_events"``.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        schema: str,
        source_service: str,
        table_name: str = "undelivered_events",
    ) -> None:
        self._session = session
        self._schema = schema
        self._source_service = source_service
        self._table_name = table_name

    async def publish(
        self,
        *,
        event_type: str,
        tenant_id: str,
        data: dict[str, Any],
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """Insert an event into the outbox. Returns the outbox row id.

        Raises:
            RuntimeError: If the caller's session has no open transaction.
        """
        if not self._session.in_transaction():
            raise RuntimeError(
                "DurableEventPublisher.publish must be called inside an "
                "open SQLAlchemy transaction (async with session.begin()). "
                "Publishing without a transaction breaks the outbox "
                "guarantee — the event row could commit while the caller's "
                "business data rolls back.",
            )

        event_id = uuid4()
        merged_metadata: dict[str, Any] = {"source_service": self._source_service}
        if metadata:
            merged_metadata.update(metadata)

        await self._session.execute(
            text(
                f"INSERT INTO {self._schema}.{self._table_name} "
                "(id, event_type, tenant_id, actor_id, data, metadata) "
                "VALUES (:id, :event_type, :tenant_id, :actor_id, "
                "CAST(:data AS JSONB), CAST(:metadata AS JSONB))",
            ),
            {
                "id": str(event_id),
                "event_type": event_type,
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "data": json.dumps(data),
                "metadata": json.dumps(merged_metadata),
            },
        )
        return event_id


__all__ = ["DurableEventPublisher"]
