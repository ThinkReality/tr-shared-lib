"""Shared SQLAlchemy base model + mixins: every table inherits id, tenant_id,
timestamps, audit, and soft-delete columns."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func, text


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Adding this to an existing table needs a backfill or NOT NULL fails:
    #   UPDATE <table> SET updated_at = created_at WHERE updated_at IS NULL;
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantMixin:
    """No FK — microservice isolation."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )


class AuditMixin:
    """No FK — microservice isolation."""

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class SoftDeleteMixin:
    """Never hard-DELETE rows — soft-delete only."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
        self.is_active = False

    def restore(self) -> None:
        self.deleted_at = None
        self.is_active = True


class BaseModel(Base, TimestampMixin, TenantMixin, AuditMixin, SoftDeleteMixin):
    """Inherit this, not Base — adds id plus every mixin column."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id})>"
