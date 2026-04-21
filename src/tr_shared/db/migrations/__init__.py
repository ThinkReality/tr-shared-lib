"""Migration safety helpers for Alembic.

Consolidates production-safe DDL patterns every service needs:
- concurrent_index_context: wrap CREATE INDEX CONCURRENTLY safely
- add_check_constraint_deferred / add_fk_deferred: NOT VALID + VALIDATE pattern
- dedup_with_table_lock: lock-protected row dedup
- bootstrap_schema_and_version_table: one-shot schema + version-table setup
- make_service_include_object: autogenerate filter by service schema
"""

from tr_shared.db.migrations.bootstrap import (
    UNDELIVERED_EVENTS_COLUMNS,
    bootstrap_schema_and_version_table,
)
from tr_shared.db.migrations.concurrent_index import concurrent_index_context
from tr_shared.db.migrations.constraints import (
    CrossSchemaFKError,
    add_check_constraint_deferred,
    add_fk_deferred,
)
from tr_shared.db.migrations.dedup import dedup_with_table_lock
from tr_shared.db.migrations.include_object import make_service_include_object

__all__ = [
    "CrossSchemaFKError",
    "UNDELIVERED_EVENTS_COLUMNS",
    "add_check_constraint_deferred",
    "add_fk_deferred",
    "bootstrap_schema_and_version_table",
    "concurrent_index_context",
    "dedup_with_table_lock",
    "make_service_include_object",
]
