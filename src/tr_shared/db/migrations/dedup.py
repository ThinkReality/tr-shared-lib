"""Lock-protected row dedup for Alembic migrations."""

from typing import Any, Literal

_DEFAULT_SOFT_DELETE_COLUMNS: dict[str, str] = {
    "deleted_at": "NOW()",
    "is_enabled": "FALSE",
    "is_active": "FALSE",
}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _qualified(schema: str, name: str) -> str:
    return f"{_quote(schema)}.{_quote(name)}"


def dedup_with_table_lock(
    op: Any,
    *,
    table: str,
    schema: str,
    partition_by: list[str],
    order_by: list[str],
    filter_predicate: str | None = None,
    strategy: Literal["soft_delete", "hard_delete"] = "soft_delete",
    soft_delete_columns: dict[str, str] | None = None,
) -> None:
    """Dedup rows inside a LOCK-protected transaction.

    Issues ``LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`` which blocks
    concurrent writers (INSERT/UPDATE/DELETE) but allows concurrent reads.
    Required for dedup on populated tables — plain CTE+UPDATE has a race
    window where concurrent INSERTs land after the ranking scan but before
    the UPDATE, leaving duplicates untouched.

    Args:
        op: Alembic ``op`` module.
        table: Table name (unqualified).
        schema: Schema name.
        partition_by: Columns that define a "duplicate group" (e.g.
            ``["tenant_id", "platform_name"]``).
        order_by: Raw SQL ordering clauses for the ROW_NUMBER tie-breaker
            (e.g. ``["is_enabled DESC", "updated_at DESC NULLS LAST"]``).
            The FIRST row in this ordering is kept; the rest are deduped.
        filter_predicate: Optional WHERE clause to restrict scope (e.g.
            ``"platform_name = 'PropertyFinder API'"``). Must not include
            the ``WHERE`` keyword.
        strategy: ``"soft_delete"`` sets soft-delete columns on losers;
            ``"hard_delete"`` issues DELETE FROM.
        soft_delete_columns: Map of column -> SQL expression to set on
            losers. Defaults to
            ``{"deleted_at": "NOW()", "is_enabled": "FALSE",
            "is_active": "FALSE"}``. Ignored when strategy=hard_delete.

    The helper emits a RAISE NOTICE with the losers-count to alembic
    build logs for audit.

    Transaction note:
        LOCK TABLE is valid only inside a transaction. Alembic wraps
        every migration in a transaction by default, so no extra setup
        is required. Do NOT call this inside an autocommit_block().
    """
    qtable = _qualified(schema, table)
    partition_cols = ", ".join(_quote(c) for c in partition_by)
    order_clause = ", ".join(order_by)
    where_clause = f"WHERE {filter_predicate}" if filter_predicate else ""

    # LOCK first so no concurrent writer can race between ranking and update.
    op.execute(f"LOCK TABLE {qtable} IN SHARE ROW EXCLUSIVE MODE")

    if strategy == "hard_delete":
        action_sql = (
            f"DELETE FROM {qtable} t "
            "USING ranked "
            "WHERE t.id = ranked.id AND ranked.rn > 1"
        )
    elif strategy == "soft_delete":
        cols = soft_delete_columns or _DEFAULT_SOFT_DELETE_COLUMNS
        set_clause = ", ".join(
            f"{_quote(col)} = {expr}" for col, expr in cols.items()
        )
        action_sql = (
            f"UPDATE {qtable} t SET {set_clause} "
            "FROM ranked "
            "WHERE t.id = ranked.id AND ranked.rn > 1"
        )
    else:
        raise ValueError(
            f"Unknown dedup strategy: {strategy!r} "
            "(expected 'soft_delete' or 'hard_delete')",
        )

    op.execute(
        f"""
        DO $$
        DECLARE
            loser_count INT;
        BEGIN
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY {partition_cols}
                           ORDER BY {order_clause}
                       ) AS rn
                FROM {qtable}
                {where_clause}
            ),
            losers AS (
                SELECT id FROM ranked WHERE rn > 1
            )
            SELECT COUNT(*) INTO loser_count FROM losers;

            RAISE NOTICE 'dedup_with_table_lock: % losers in %',
                         loser_count, '{schema}.{table}';
        END $$;
        """,
    )

    op.execute(
        f"""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY {partition_cols}
                       ORDER BY {order_clause}
                   ) AS rn
            FROM {qtable}
            {where_clause}
        )
        {action_sql}
        """,
    )
