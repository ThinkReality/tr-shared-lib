"""Shared database utilities — base model, session factory, repository."""

from tr_shared.db.base import (
    AuditMixin,
    BaseModel,
    SoftDeleteMixin,
    TimestampMixin,
    TenantMixin,
)
from tr_shared.db.repository import BaseRepository
from tr_shared.db.session import create_async_engine_factory, create_session_factory, get_db
from tr_shared.db.utils import to_migration_url, to_session_mode_url, to_sync_url

__all__ = [
    "AuditMixin",
    "BaseModel",
    "BaseRepository",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "create_async_engine_factory",
    "create_session_factory",
    "get_db",
    "to_migration_url",
    "to_session_mode_url",
    "to_sync_url",
]
