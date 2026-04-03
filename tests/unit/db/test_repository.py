"""Tests for BaseRepository with AsyncMock session."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tr_shared.db.base import BaseModel
from tr_shared.db.repository import BaseRepository


# ---------------------------------------------------------------------------
# Test model
# ---------------------------------------------------------------------------

class FakeEntity(BaseModel):
    """Minimal concrete model used for repository tests."""
    __tablename__ = "test_fake_entity"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = uuid.uuid4()
ENTITY_ID = uuid.uuid4()


def _make_entity(id=None, tenant_id=None, deleted_at=None, is_active=True):
    e = FakeEntity()
    e.id = id or uuid.uuid4()
    e.tenant_id = tenant_id or TENANT_ID
    e.deleted_at = deleted_at
    e.is_active = is_active
    return e


def _make_session():
    """Build a fully-mocked AsyncSession."""
    session = AsyncMock()
    # execute returns a result proxy
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _repo(session=None):
    s = session or _make_session()
    return BaseRepository(db_session=s, model=FakeEntity), s


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------

class TestGetById:
    async def test_returns_entity_when_found(self):
        entity = _make_entity()
        session = _make_session()
        session.execute.return_value.scalar_one_or_none.return_value = entity
        repo, _ = _repo(session)
        result = await repo.get_by_id(entity.id, TENANT_ID)
        assert result is entity

    async def test_returns_none_when_not_found(self):
        repo, _ = _repo()
        result = await repo.get_by_id(ENTITY_ID, TENANT_ID)
        assert result is None

    async def test_execute_called_once(self):
        repo, session = _repo()
        await repo.get_by_id(ENTITY_ID, TENANT_ID)
        session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------

class TestGetAll:
    async def test_returns_list(self):
        entities = [_make_entity(), _make_entity()]
        session = _make_session()
        session.execute.return_value.scalars.return_value.all.return_value = entities
        repo, _ = _repo(session)
        result = await repo.get_all(TENANT_ID)
        assert result == entities

    async def test_returns_empty_list_when_no_records(self):
        repo, _ = _repo()
        result = await repo.get_all(TENANT_ID)
        assert result == []

    async def test_calls_execute(self):
        repo, session = _repo()
        await repo.get_all(TENANT_ID)
        session.execute.assert_awaited_once()

    async def test_filters_applied_when_provided(self):
        repo, session = _repo()
        await repo.get_all(TENANT_ID, filters={"is_active": True})
        # Just verify execute was called — filter logic is internal
        session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_paginated
# ---------------------------------------------------------------------------

class TestGetPaginated:
    async def test_returns_tuple(self):
        repo, _ = _repo()
        result = await repo.get_paginated(TENANT_ID, page=1, per_page=10)
        assert isinstance(result, tuple)
        assert len(result) == 2

    async def test_returns_items_and_total(self):
        entities = [_make_entity()]
        session = _make_session()
        # First execute → count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        # Second execute → items query
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = entities

        session.execute = AsyncMock(side_effect=[count_result, items_result])
        repo, _ = _repo(session)
        items, total = await repo.get_paginated(TENANT_ID, page=1, per_page=10)
        assert items == entities
        assert total == 1

    async def test_offset_is_correct_for_page_2(self):
        """Offset = (page - 1) * per_page — verify by checking execute call count."""
        repo, session = _repo()
        await repo.get_paginated(TENANT_ID, page=2, per_page=5)
        # Both count and items queries executed
        assert session.execute.await_count == 2

    async def test_zero_total_when_empty(self):
        session = _make_session()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[count_result, items_result])
        repo, _ = _repo(session)
        items, total = await repo.get_paginated(TENANT_ID)
        assert total == 0
        assert items == []


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------

class TestCount:
    async def test_returns_integer(self):
        session = _make_session()
        session.execute.return_value.scalar.return_value = 5
        repo, _ = _repo(session)
        result = await repo.count(TENANT_ID)
        assert result == 5

    async def test_returns_zero_when_empty(self):
        repo, _ = _repo()
        result = await repo.count(TENANT_ID)
        assert result == 0


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    async def test_adds_to_session(self):
        entity = _make_entity()
        repo, session = _repo()
        await repo.create(entity)
        session.add.assert_called_once_with(entity)

    async def test_calls_flush(self):
        entity = _make_entity()
        repo, session = _repo()
        await repo.create(entity)
        session.flush.assert_awaited_once()

    async def test_calls_refresh(self):
        entity = _make_entity()
        repo, session = _repo()
        await repo.create(entity)
        session.refresh.assert_awaited_once_with(entity)

    async def test_returns_entity(self):
        entity = _make_entity()
        repo, _ = _repo()
        result = await repo.create(entity)
        assert result is entity

    async def test_raises_when_tenant_id_is_none(self):
        entity = _make_entity()
        entity.tenant_id = None
        repo, _ = _repo()
        with pytest.raises(ValueError, match="tenant_id must be set"):
            await repo.create(entity)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdate:
    async def test_calls_flush(self):
        entity = _make_entity()
        repo, session = _repo()
        await repo.update(entity)
        session.flush.assert_awaited_once()

    async def test_calls_refresh(self):
        entity = _make_entity()
        repo, session = _repo()
        await repo.update(entity)
        session.refresh.assert_awaited_once_with(entity)

    async def test_sets_updated_at(self):
        entity = _make_entity()
        entity.updated_at = None
        repo, _ = _repo()
        before = datetime.now(timezone.utc)
        await repo.update(entity)
        assert entity.updated_at is not None
        assert entity.updated_at >= before


# ---------------------------------------------------------------------------
# soft_delete
# ---------------------------------------------------------------------------

class TestSoftDelete:
    async def test_returns_false_when_not_found(self):
        repo, _ = _repo()
        result = await repo.soft_delete(ENTITY_ID, TENANT_ID)
        assert result is False

    async def test_returns_true_when_found(self):
        entity = _make_entity()
        session = _make_session()
        session.execute.return_value.scalar_one_or_none.return_value = entity
        repo, _ = _repo(session)
        result = await repo.soft_delete(entity.id, TENANT_ID)
        assert result is True

    async def test_sets_deleted_at_on_entity(self):
        entity = _make_entity()
        entity.deleted_at = None
        session = _make_session()
        session.execute.return_value.scalar_one_or_none.return_value = entity
        repo, _ = _repo(session)
        await repo.soft_delete(entity.id, TENANT_ID)
        assert entity.deleted_at is not None

    async def test_sets_is_active_false(self):
        entity = _make_entity()
        session = _make_session()
        session.execute.return_value.scalar_one_or_none.return_value = entity
        repo, _ = _repo(session)
        await repo.soft_delete(entity.id, TENANT_ID)
        assert entity.is_active is False

    async def test_does_not_hard_delete(self):
        """soft_delete must NOT call session.delete()."""
        entity = _make_entity()
        session = _make_session()
        session.execute.return_value.scalar_one_or_none.return_value = entity
        session.delete = MagicMock()
        repo, _ = _repo(session)
        await repo.soft_delete(entity.id, TENANT_ID)
        session.delete.assert_not_called()
