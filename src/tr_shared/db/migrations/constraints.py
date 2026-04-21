"""Deferred CHECK / FK constraint helpers.

NOT VALID + VALIDATE CONSTRAINT decouples the lock from the validation scan,
so ops can interrupt VALIDATE without leaving the constraint in a broken
state. Required for any CHECK/FK added to a populated table.
"""

from typing import Any


class CrossSchemaFKError(ValueError):
    """Raised when add_fk_deferred is called with a cross-schema reference.

    Per TR standards (common_docs/TR_Standards.md) no FK may cross service
    schemas — each service owns its schema and tenant isolation is enforced
    at the application layer.
    """


def _quote(identifier: str) -> str:
    """Quote a SQL identifier with double quotes, escaping embedded quotes."""
    return '"' + identifier.replace('"', '""') + '"'


def _qualified(schema: str, name: str) -> str:
    """Return schema-qualified quoted identifier."""
    return f"{_quote(schema)}.{_quote(name)}"


def add_check_constraint_deferred(
    op: Any,
    *,
    table: str,
    schema: str,
    constraint_name: str,
    predicate: str,
) -> None:
    """Add a CHECK constraint via NOT VALID + VALIDATE CONSTRAINT.

    Step 1: ``ALTER TABLE ... ADD CONSTRAINT ... CHECK (...) NOT VALID``
            acquires a brief ACCESS EXCLUSIVE lock but does NOT scan the
            table — fast even on large tables.
    Step 2: ``ALTER TABLE ... VALIDATE CONSTRAINT ...`` scans the table
            under SHARE UPDATE EXCLUSIVE (allows reads + writes of
            unaffected rows). Safe to interrupt; constraint stays INVALID
            until re-validated.

    Args:
        op: Alembic ``op`` module.
        table: Table name (unqualified).
        schema: Schema name.
        constraint_name: Constraint name. Caller owns uniqueness.
        predicate: SQL predicate (the part inside ``CHECK (...)``).

    Usage::

        add_check_constraint_deferred(
            op,
            table="admin_panel_listing_platform_configs",
            schema="admin",
            constraint_name="ck_platform_name_known",
            predicate="platform_name IN ('PropertyFinder API', 'Google Gemini AI')",
        )
    """
    qtable = _qualified(schema, table)
    qname = _quote(constraint_name)
    op.execute(
        f"ALTER TABLE {qtable} "
        f"ADD CONSTRAINT {qname} CHECK ({predicate}) NOT VALID",
    )
    op.execute(f"ALTER TABLE {qtable} VALIDATE CONSTRAINT {qname}")


def add_fk_deferred(
    op: Any,
    *,
    table: str,
    schema: str,
    constraint_name: str,
    columns: list[str],
    ref_table: str,
    ref_schema: str,
    ref_columns: list[str],
    on_delete: str | None = None,
) -> None:
    """Add a FOREIGN KEY via NOT VALID + VALIDATE CONSTRAINT.

    Cross-schema FKs are refused per TR standards: no FK may cross service
    schemas. Tenant isolation is enforced at the application layer, not
    via DB-level FK constraints to foreign services' tables.

    Args:
        op: Alembic ``op`` module.
        table: Table name (unqualified).
        schema: Schema of the owning table.
        constraint_name: Constraint name. Caller owns uniqueness.
        columns: Local columns in the FK.
        ref_table: Referenced table name.
        ref_schema: Referenced table schema. Must equal ``schema``.
        ref_columns: Referenced columns.
        on_delete: Optional referential action ('CASCADE', 'SET NULL', etc).

    Raises:
        CrossSchemaFKError: If ``ref_schema != schema``.
    """
    if ref_schema != schema:
        raise CrossSchemaFKError(
            f"FK from {schema}.{table} to {ref_schema}.{ref_table} crosses "
            "service schemas. TR standards forbid cross-service FKs — "
            "enforce referential integrity at the application layer. "
            "See common_docs/TR_Standards.md.",
        )

    qtable = _qualified(schema, table)
    qname = _quote(constraint_name)
    qref = _qualified(ref_schema, ref_table)
    cols = ", ".join(_quote(c) for c in columns)
    ref_cols = ", ".join(_quote(c) for c in ref_columns)

    on_delete_clause = ""
    if on_delete:
        on_delete_clause = f" ON DELETE {on_delete}"

    op.execute(
        f"ALTER TABLE {qtable} "
        f"ADD CONSTRAINT {qname} FOREIGN KEY ({cols}) "
        f"REFERENCES {qref} ({ref_cols})"
        f"{on_delete_clause} NOT VALID",
    )
    op.execute(f"ALTER TABLE {qtable} VALIDATE CONSTRAINT {qname}")
