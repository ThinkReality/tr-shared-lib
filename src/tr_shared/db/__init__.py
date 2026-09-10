"""Shared database utilities — base model, session factory, repository, migrations."""

from tr_shared.db.base import (
    AuditMixin,
    Base,
    BaseModel,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
)
from tr_shared.db.migrations import (
    assert_migrations_are_merged,
    bootstrap_schema_and_version_table,
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
    LOCAL_DB_HOST_PREFIX,
    LOCAL_DB_HOSTS,
    escape_like,
    is_local_dsn,
    to_migration_url,
    to_session_mode_url,
    to_sync_url,
)

__all__ = [
    "AuditMixin",
    "Base",
    "BaseModel",
    "BaseRepository",
    "LIKE_ESCAPE_CHAR",
    "LOCAL_DB_HOSTS",
    "LOCAL_DB_HOST_PREFIX",
    "PGBOUNCER_CONNECT_ARGS",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "assert_migrations_are_merged",
    "bootstrap_schema_and_version_table",
    "create_async_engine_factory",
    "create_session_factory",
    "escape_like",
    "get_db",
    "is_local_dsn",
    "make_service_include_object",
    "run_async_migrations",
    "to_migration_url",
    "to_session_mode_url",
    "to_sync_url",
]
