"""Autogenerate filter: keep only objects that belong to the service schema."""

from collections.abc import Callable
from typing import Any

try:  # SQLAlchemy is a peer dependency; keep the import optional.
    from sqlalchemy import MetaData
except ImportError:  # pragma: no cover — service environments always have it.
    MetaData = Any  # type: ignore[assignment,misc]


def make_service_include_object(
    target_schema: str,
    target_metadata: "MetaData",
) -> Callable[[Any, str, str, bool, Any], bool]:
    """Return an ``include_object`` callable for Alembic's ``context.configure``.

    Filters every object Alembic considers during autogenerate down to the
    service's own schema + only those objects already declared in
    ``target_metadata``. Covers:

    - tables
    - indexes (via ``object.table.schema``)
    - unique constraints, foreign keys, check constraints (via ``.table.schema``)
    - sequences (via ``object.schema``)

    Rationale: the default include_object in tr-be-admin-panel's env.py
    before this helper only filtered tables — indexes, constraints, and
    sequences from other services' schemas slipped through when
    ``include_schemas=True`` was set, polluting autogenerate diffs.

    Args:
        target_schema: The service schema (e.g. ``"admin"``).
        target_metadata: The service's SQLAlchemy ``Base.metadata``. Objects
            not present in metadata are rejected even if their schema
            matches — guards against reflection picking up rogue objects.

    Usage in env.py::

        from tr_shared.db.migrations import make_service_include_object

        include_object = make_service_include_object("admin", target_metadata)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            ...
        )
    """
    own_table_names: frozenset[str] = frozenset(
        t.name
        for t in target_metadata.sorted_tables
        if getattr(t, "schema", None) == target_schema
    )

    def include_object(
        obj: Any,
        name: str,
        type_: str,
        reflected: bool,  # noqa: ARG001 — part of Alembic API
        compare_to: Any,  # noqa: ARG001 — part of Alembic API
    ) -> bool:
        if type_ == "table":
            schema = getattr(obj, "schema", None)
            return schema == target_schema and name in own_table_names

        # Indexes / unique constraints / FKs / CHECKs all carry a .table ref.
        parent_table = getattr(obj, "table", None)
        if parent_table is not None:
            parent_schema = getattr(parent_table, "schema", None)
            if parent_schema != target_schema:
                return False
            return parent_table.name in own_table_names

        # Sequences expose .schema directly.
        obj_schema = getattr(obj, "schema", None)
        if obj_schema is not None:
            return obj_schema == target_schema

        # Unknown object type with no schema / parent — let Alembic decide.
        return True

    return include_object
