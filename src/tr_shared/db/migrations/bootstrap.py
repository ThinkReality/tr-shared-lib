"""Schema + version-table bootstrap for alembic/env.py.

Replaces the fragile double-commit pattern that every service's env.py
reinvents. Owns its own short transaction; does not interact with
Alembic's migration transaction.
"""

from typing import Any, Literal

from sqlalchemy import text


UNDELIVERED_EVENTS_COLUMNS: str = """
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    tenant_id UUID NOT NULL,
    actor_id UUID,
    data JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    retry_count INT NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dead_letter BOOLEAN NOT NULL DEFAULT FALSE,
    last_error TEXT
"""
"""Required columns for the per-service undelivered_events outbox table.

Each service creates ``{service_schema}.undelivered_events`` in its own
Alembic migration using this column list to stay wire-compatible with
``tr_shared.events.DurableEventPublisher``. Also create a partial index::

    CREATE INDEX idx_{service}_undelivered_due
    ON {schema}.undelivered_events (next_retry_at)
    WHERE published_at IS NULL AND dead_letter = FALSE;
"""


def bootstrap_schema_and_version_table(
    connection: Any,
    *,
    schema: str,
    version_table: str,
    legacy_schema: str = "public",
) -> Literal["target", "legacy", "absent"]:
    """Create the service schema and ensure the Alembic version table lives in it.

    Steps (all idempotent):

    1. ``CREATE SCHEMA IF NOT EXISTS {schema}``
    2. If ``{version_table}`` exists in ``{legacy_schema}`` and NOT in
       ``{schema}``: ``ALTER TABLE ... SET SCHEMA`` to move it.
    3. Commit the bootstrap transaction so the subsequent ``context.configure``
       sees a clean slate.

    Return value tells the caller where the version table lives *now*:

    - ``"target"``  — version table is in ``{schema}`` (normal operation
      after first migration ran).
    - ``"legacy"``  — version table is still in ``{legacy_schema}`` and was
      NOT moved (caller should pass ``version_table_schema=legacy_schema``
      to Alembic for this run). This only occurs when the ``schema`` has
      not yet been created when the version table was originally created
      by Alembic — the caller should use the legacy location and let the
      next migration move it.
    - ``"absent"``  — version table does not exist in either location
      (first-ever run). Caller passes ``version_table_schema=schema`` so
      Alembic creates it in the right place from the start.

    Usage in env.py::

        from tr_shared.db.migrations import bootstrap_schema_and_version_table

        def do_run_migrations(connection):
            where = bootstrap_schema_and_version_table(
                connection,
                schema="admin",
                version_table="alembic_version_admin_panel",
            )
            vt_schema = "admin" if where in ("target", "absent") else "public"
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table="alembic_version_admin_panel",
                version_table_schema=vt_schema,
                include_schemas=True,
                include_object=include_object,
            )
            with context.begin_transaction():
                context.run_migrations()

    Args:
        connection: SQLAlchemy ``Connection`` — sync or the driver-level
            connection inside ``connection.run_sync(do_run_migrations)``.
        schema: Target service schema (e.g. ``"admin"``).
        version_table: Alembic version table name (e.g.
            ``"alembic_version_admin_panel"``).
        legacy_schema: Schema to check for a pre-existing version table
            and migrate from. Defaults to ``"public"``.
    """
    # Step 1 — create target schema (idempotent).
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    # Step 2 — detect where the version table lives.
    in_target = connection.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :table",
        ),
        {"schema": schema, "table": version_table},
    ).scalar()

    in_legacy = connection.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :table",
        ),
        {"schema": legacy_schema, "table": version_table},
    ).scalar()

    location: Literal["target", "legacy", "absent"]

    if in_target:
        location = "target"
    elif in_legacy:
        # Move it — ALTER TABLE SET SCHEMA is atomic + carries all
        # indexes, constraints, sequences, triggers, RLS, privileges.
        connection.execute(
            text(
                f'ALTER TABLE "{legacy_schema}"."{version_table}" '
                f'SET SCHEMA "{schema}"',
            ),
        )
        location = "target"
    else:
        location = "absent"

    # Step 3 — commit bootstrap so context.begin_transaction() later opens
    # a clean migration transaction without entangling with DDL above.
    connection.commit()

    return location
