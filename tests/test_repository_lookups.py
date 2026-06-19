"""Unit tests for BaseRepository generic lookups (find_by_field / _in / get_all order).

No live DB: a fake session captures the built SQLAlchemy statement so we can
assert tenant scoping, soft-delete filtering, and ordering on the constructed
query without a Postgres round-trip.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tr_shared.db import BaseRepository


class _Base(DeclarativeBase):
    pass


class Widget(_Base):
    __tablename__ = "widgets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.last_stmt = None
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        self.last_stmt = stmt
        return _FakeResult(self.rows)


@pytest.fixture
def tid():
    return uuid4()


async def test_find_by_field_scopes_tenant_and_soft_delete(tid):
    session = _FakeSession()
    repo = BaseRepository(db_session=session, model=Widget)

    await repo.find_by_field("name", "alpha", tid)

    sql = str(session.last_stmt)
    assert "widgets.name" in sql
    assert "widgets.tenant_id" in sql
    assert "widgets.deleted_at IS NULL" in sql


async def test_find_by_field_in_empty_short_circuits(tid):
    session = _FakeSession()
    repo = BaseRepository(db_session=session, model=Widget)

    result = await repo.find_by_field_in("name", [], tid)

    assert result == []
    assert session.calls == 0  # no query issued


async def test_find_by_field_in_builds_in_clause(tid):
    session = _FakeSession()
    repo = BaseRepository(db_session=session, model=Widget)

    await repo.find_by_field_in("name", ["a", "b"], tid)

    sql = str(session.last_stmt)
    assert "widgets.name IN" in sql
    assert "widgets.tenant_id" in sql
    assert "widgets.deleted_at IS NULL" in sql


async def test_unknown_field_raises_value_error(tid):
    session = _FakeSession()
    repo = BaseRepository(db_session=session, model=Widget)

    with pytest.raises(ValueError, match="no column 'nope'"):
        await repo.find_by_field("nope", "x", tid)


async def test_get_all_orders_ascending(tid):
    session = _FakeSession()
    repo = BaseRepository(db_session=session, model=Widget)

    await repo.get_all(tid, order_by="name", descending=False)

    sql = str(session.last_stmt)
    assert "ORDER BY widgets.name ASC" in sql


async def test_get_all_unknown_order_by_ignored(tid):
    session = _FakeSession()
    repo = BaseRepository(db_session=session, model=Widget)

    await repo.get_all(tid, order_by="nonexistent")

    sql = str(session.last_stmt)
    assert "ORDER BY" not in sql
