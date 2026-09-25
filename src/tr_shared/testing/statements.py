"""Count the SQL statements a block of code sends, across every engine in the process."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def record_statements() -> Iterator[list[str]]:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    seen: list[str] = []

    def _record(conn: Any, cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", _record)


def describe_statements(seen: list[str]) -> str:
    return "\n".join(f"{i + 1:>2}. {s.split(chr(10))[0][:110]}" for i, s in enumerate(seen))
