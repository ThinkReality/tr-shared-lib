"""Migration safety helpers for Alembic.

Consolidates production-safe DDL patterns every service needs:
- bootstrap_schema_and_version_table: one-shot schema + version-table setup
- make_service_include_object: autogenerate filter by service schema
- make_service_include_name: autogenerate schema-reflection filter (quiets shared-DB noise)
- assert_migrations_are_merged: fail the build on an unmerged multi-head chain
- run_async_migrations: async engine entry point for env.py
"""

from tr_shared.db.migrations.bootstrap import bootstrap_schema_and_version_table
from tr_shared.db.migrations.include_object import (
    make_service_include_name,
    make_service_include_object,
)
from tr_shared.db.migrations.merge_gate import assert_migrations_are_merged
from tr_shared.db.migrations.runner import run_async_migrations

__all__ = [
    "assert_migrations_are_merged",
    "bootstrap_schema_and_version_table",
    "make_service_include_name",
    "make_service_include_object",
    "run_async_migrations",
]
