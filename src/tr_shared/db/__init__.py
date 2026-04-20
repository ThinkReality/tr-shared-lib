"""Shared database utilities — base model, session factory, repository."""

from tr_shared.db.base import (
    AuditMixin,
    Base,
    BaseModel,
    SoftDeleteMixin,
    TimestampMixin,
    TenantMixin,
)
from tr_shared.db.repository import BaseRepository
from tr_shared.db.session import (
    PGBOUNCER_CONNECT_ARGS,
    create_async_engine_factory,
    create_session_factory,
    get_db,
)
from tr_shared.db.utils import to_migration_url, to_session_mode_url, to_sync_url

__all__ = [
    "AuditMixin",
    "Base",
    "BaseModel",
    "BaseRepository",
    "PGBOUNCER_CONNECT_ARGS",
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
