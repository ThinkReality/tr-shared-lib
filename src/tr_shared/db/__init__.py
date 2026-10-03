"""Shared database utilities — base model, session factory, repository, migrations."""

from tr_shared.db.base import (
    AuditMixin,
    Base,
    BaseModel,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from tr_shared.db.errors import (
    DATABASE_OUTAGE_ERRORS,
    DatabaseTimeoutError,
    DatabaseUnavailableError,
)
from tr_shared.db.migrations import (
    assert_migrations_are_merged,
    bootstrap_schema_and_version_table,
    make_service_include_object,
    run_async_migrations,
)
from tr_shared.db.repository import BaseRepository
from tr_shared.db.session import (
    DEFAULT_POOL_KWARGS,
    PGBOUNCER_CONNECT_ARGS,
    OutageTypedQueuePool,
    create_async_engine_factory,
    create_session_factory,
    dispose_engines_after_fork,
    get_db,
    prepare_sync_engine,
    set_local_statement_timeout_sql,
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
    "DATABASE_OUTAGE_ERRORS",
    "DatabaseTimeoutError",
    "DatabaseUnavailableError",
    "LIKE_ESCAPE_CHAR",
    "LOCAL_DB_HOSTS",
    "LOCAL_DB_HOST_PREFIX",
    "DEFAULT_POOL_KWARGS",
    "OutageTypedQueuePool",
    "PGBOUNCER_CONNECT_ARGS",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "assert_migrations_are_merged",
    "bootstrap_schema_and_version_table",
    "create_async_engine_factory",
    "dispose_engines_after_fork",
    "create_session_factory",
    "escape_like",
    "get_db",
    "is_local_dsn",
    "make_service_include_object",
    "prepare_sync_engine",
    "run_async_migrations",
    "set_local_statement_timeout_sql",
    "to_migration_url",
    "to_session_mode_url",
    "to_sync_url",
    "UUIDPrimaryKeyMixin",
]
