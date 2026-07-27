"""S1 guard: BaseRepository must reject ``tenant_id=None`` loudly.

Without the guard the query renders ``tenant_id IS NULL`` against a NOT NULL
column — it fails closed, but silently, so a caller that lost its tenant sees
an empty result set instead of a stack trace.
"""

from datetime import datetime

import pytest
from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tr_shared.db import BaseRepository


class _Base(DeclarativeBase):
    pass


class Gadget(_Base):
    __tablename__ = "gadgets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _FakeSession:
    def __init__(self):
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        raise AssertionError("query must never be issued without a tenant_id")


@pytest.fixture
def repo():
    return BaseRepository(db_session=_FakeSession(), model=Gadget)


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_by_id", ("some-id",)),
        ("get_all", ()),
        ("find_by_field", ("name", "alpha")),
        ("find_by_field_in", ("name", ["a"])),
        ("get_paginated", ()),
        ("count", ()),
        ("soft_delete", ("some-id",)),
    ],
)
async def test_none_tenant_raises_value_error(repo, method, args):
    with pytest.raises(ValueError, match="tenant_id is required"):
        await getattr(repo, method)(*args, tenant_id=None)

    assert repo.db_session.calls == 0
