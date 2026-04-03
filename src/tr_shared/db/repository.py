"""
Shared tenant-scoped base repository.

Extracted from tr-lead-management (the most complete: pagination, soft-delete,
generic typing). Key improvement: ``tenant_id`` is **mandatory** on every query
method — fixing the crm-backend security gap where tenant_id was optional.

Usage::

    from tr_shared.db import BaseRepository

    class LeadRepository(BaseRepository[Lead]):
        pass

    repo = LeadRepository(db_session=session, model=Lead)
    leads, total = await repo.get_paginated(tenant_id=tid, page=1)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

T = TypeVar("T", bound=DeclarativeBase)


class BaseRepository(Generic[T]):
    """
    Generic async repository with mandatory tenant scoping.

    Every read/write operation requires ``tenant_id`` to enforce
    multi-tenant isolation at the data-access layer.
    """

    def __init__(self, db_session: AsyncSession, model: type[T]) -> None:
        self.db_session = db_session
        self.model = model
        self.logger = logging.getLogger(self.__class__.__name__)

    # ── Read ─────────────────────────────────────────────────────────

    async def get_by_id(self, id: UUID, tenant_id: UUID) -> T | None:
        """Get a single entity by ID, scoped to tenant."""
        query = select(self.model).where(
            self.model.id == id,
            self.model.tenant_id == tenant_id,
        )
        if hasattr(self.model, "deleted_at"):
            query = query.where(self.model.deleted_at.is_(None))
        result = await self.db_session.execute(query)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        tenant_id: UUID,
        filters: dict[str, Any] | None = None,
    ) -> list[T]:
        """Get all non-deleted entities for a tenant."""
        query = select(self.model).where(self.model.tenant_id == tenant_id)
        if hasattr(self.model, "deleted_at"):
            query = query.where(self.model.deleted_at.is_(None))
        if filters:
            query = self._apply_filters(query, filters)
        result = await self.db_session.execute(query)
        return list(result.scalars().all())

    async def get_paginated(
        self,
        tenant_id: UUID,
        page: int = 1,
        per_page: int = 20,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> tuple[list[T], int]:
        """Return ``(items, total_count)`` with pagination."""
        query = select(self.model).where(self.model.tenant_id == tenant_id)
        if hasattr(self.model, "deleted_at"):
            query = query.where(self.model.deleted_at.is_(None))
        if filters:
            query = self._apply_filters(query, filters)

        # Total count
        count_q = select(func.count()).select_from(query.alias())
        total = (await self.db_session.execute(count_q)).scalar() or 0

        # Ordering
        if order_by and hasattr(self.model, order_by):
            query = query.order_by(getattr(self.model, order_by).desc())
        elif hasattr(self.model, "created_at"):
            query = query.order_by(self.model.created_at.desc())

        # Pagination
        offset = (page - 1) * per_page
        query = query.limit(per_page).offset(offset)

        items = list((await self.db_session.execute(query)).scalars().all())
        return items, total

    async def count(
        self,
        tenant_id: UUID,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count entities for a tenant."""
        query = select(func.count()).select_from(self.model).where(
            self.model.tenant_id == tenant_id,
        )
        if hasattr(self.model, "deleted_at"):
            query = query.where(self.model.deleted_at.is_(None))
        if filters:
            query = self._apply_filters(query, filters)
        return (await self.db_session.execute(query)).scalar() or 0

    # ── Write ────────────────────────────────────────────────────────

    async def create(self, entity: T) -> T:
        """Add a new entity (caller must set tenant_id on the entity)."""
        if hasattr(entity, "tenant_id") and entity.tenant_id is None:
            raise ValueError(
                f"{type(entity).__name__}.tenant_id must be set before create()"
            )
        self.db_session.add(entity)
        await self.db_session.flush()
        await self.db_session.refresh(entity)
        return entity

    async def update(self, entity: T) -> T:
        """Flush pending changes on an already-tracked entity."""
        if hasattr(entity, "updated_at"):
            entity.updated_at = datetime.now(timezone.utc)
        await self.db_session.flush()
        await self.db_session.refresh(entity)
        return entity

    async def soft_delete(self, id: UUID, tenant_id: UUID) -> bool:
        """Soft-delete by setting deleted_at. Returns False if not found."""
        entity = await self.get_by_id(id, tenant_id)
        if entity is None:
            return False
        if hasattr(entity, "deleted_at"):
            entity.deleted_at = datetime.now(timezone.utc)
        if hasattr(entity, "is_active"):
            entity.is_active = False
        if hasattr(entity, "updated_at"):
            entity.updated_at = datetime.now(timezone.utc)
        await self.db_session.flush()
        return True

    # ── Internal ─────────────────────────────────────────────────────

    def _apply_filters(self, query, filters: dict[str, Any]):
        for key, value in filters.items():
            if value is not None and hasattr(self.model, key):
                query = query.where(getattr(self.model, key) == value)
        return query
