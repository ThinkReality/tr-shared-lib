"""
Shared SQLAlchemy base model with standard mixins.

Extracted from tr-lead-management (most complete: all four mixins)
and tr-media-service (soft_delete/restore helpers).

Every table gets: id, tenant_id, created_at, updated_at, created_by,
updated_by, deleted_at, is_active — by default.

Usage::

    from tr_shared.db import BaseModel

    class Lead(BaseModel):
        __tablename__ = "lead_leads"
        name = Column(String(255), nullable=False)
        # id, tenant_id, timestamps, audit, soft-delete all inherited
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func, text


class Base(DeclarativeBase):
    """Root declarative base for all services."""
    pass


class TimestampMixin:
    """created_at (auto), updated_at (auto on update)."""

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # server_default ensures non-NULL on first insert; onupdate refreshes on changes.
    # When adding server_default to existing tables, run a backfill migration:
    #   UPDATE <table> SET updated_at = created_at WHERE updated_at IS NULL;
    #   ALTER TABLE <table> ALTER COLUMN updated_at SET DEFAULT now();
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantMixin:
    """Non-nullable tenant_id (UUID, indexed). No FK per microservice isolation."""

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )


class AuditMixin:
    """created_by / updated_by user UUIDs. No FK per microservice isolation."""

    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)


class SoftDeleteMixin:
    """deleted_at timestamp + is_active boolean. Never hard-DELETE rows."""

    deleted_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))


class BaseModel(Base, TimestampMixin, TenantMixin, AuditMixin, SoftDeleteMixin):
    """
    Abstract base model providing id, tenant_id, timestamps, audit, soft-delete.

    All service models should inherit from this instead of ``Base`` directly.
    """

    __abstract__ = True

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    def soft_delete(self) -> None:
        """Mark the record as soft-deleted."""
        self.deleted_at = datetime.now(timezone.utc)
        self.is_active = False

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None
        self.is_active = True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id})>"
