"""A primary key with a server default is never SQLAlchemy's insertmanyvalues sentinel."""

from __future__ import annotations

from typing import Any


def assert_no_server_default_primary_keys(*metadata: Any) -> None:
    offenders = sorted(
        f"{table.fullname}.{column.name}"
        for meta in metadata
        for table in meta.tables.values()
        for column in table.primary_key.columns
        if column.server_default is not None
    )
    assert not offenders, "primary key carries a server_default:\n" + "\n".join(offenders)
