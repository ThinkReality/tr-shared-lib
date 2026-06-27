"""Shared database utilities — base model, session factory, repository, migrations."""

from tr_shared.db.base import (
    AuditMixin,
    Base,
    BaseModel,
    SoftDeleteMixin,
    TimestampMixin,
    TenantMixin,
)
from tr_shared.db.migrations import (
    CrossSchemaFKError,
    UNDELIVERED_EVENTS_COLUMNS,
    add_check_constraint_deferred,
    add_fk_deferred,
    bootstrap_schema_and_version_table,
    concurrent_index_context,
    dedup_with_table_lock,
    make_service_include_object,
    run_async_migrations,
)
from tr_shared.db.repository import BaseRepository
from tr_shared.db.session import (
    PGBOUNCER_CONNECT_ARGS,
    create_async_engine_factory,
    create_session_factory,
    get_db,
)
from tr_shared.db.utils import (
    LIKE_ESCAPE_CHAR,
    escape_like,
    to_migration_url,
    to_session_mode_url,
    to_sync_url,
)

__all__ = [
    "AuditMixin",
    "Base",
    "BaseModel",
    "BaseRepository",
    "CrossSchemaFKError",
    "LIKE_ESCAPE_CHAR",
    "PGBOUNCER_CONNECT_ARGS",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "UNDELIVERED_EVENTS_COLUMNS",
    "add_check_constraint_deferred",
    "add_fk_deferred",
    "bootstrap_schema_and_version_table",
    "concurrent_index_context",
    "create_async_engine_factory",
    "create_session_factory",
    "dedup_with_table_lock",
    "escape_like",
    "get_db",
    "make_service_include_object",
    "run_async_migrations",
    "to_migration_url",
    "to_session_mode_url",
    "to_sync_url",
]
