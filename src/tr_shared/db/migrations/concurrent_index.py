"""CREATE INDEX CONCURRENTLY safely inside Alembic migrations."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def concurrent_index_context(op: Any) -> Iterator[None]:
    """Context manager for CREATE INDEX CONCURRENTLY inside an Alembic migration.

    PostgreSQL's CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    Alembic wraps every migration in a transaction by default. The escape
    hatch is ``op.get_context().autocommit_block()`` — this helper wraps it
    with a clear error if the caller is outside a real Alembic migration
    context.

    Usage::

        def upgrade() -> None:
            with concurrent_index_context(op):
                op.create_index(
                    "ix_foo_bar",
                    "foo",
                    ["bar"],
                    schema="admin",
                    postgresql_concurrently=True,
                )

    The migration revision should still be declared inside a normal
    alembic migration file — no ``no_txn`` header needed; the autocommit
    block handles the transaction boundary locally.

    Raises:
        RuntimeError: If called outside an Alembic migration op context.
    """
    try:
        context = op.get_context()
    except Exception as exc:
        raise RuntimeError(
            "concurrent_index_context must be called inside an Alembic "
            "migration op context (op.get_context() unavailable)",
        ) from exc

    autocommit_block = getattr(context, "autocommit_block", None)
    if autocommit_block is None:
        raise RuntimeError(
            "Alembic context does not expose autocommit_block(); "
            "upgrade Alembic to >=1.13 or run this migration in offline mode",
        )

    with autocommit_block():
        yield
