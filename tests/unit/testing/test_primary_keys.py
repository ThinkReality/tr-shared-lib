import uuid

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase

from tr_shared.db import Base, UUIDPrimaryKeyMixin
from tr_shared.testing import assert_no_server_default_primary_keys


def test_shared_base_has_no_server_default_primary_key() -> None:
    assert_no_server_default_primary_keys(Base.metadata)


def test_mixin_id_is_client_generated() -> None:
    class ModuleBase(DeclarativeBase):
        pass

    class Row(ModuleBase, UUIDPrimaryKeyMixin):
        __tablename__ = "row"

    column = Row.__table__.c.id
    assert column.primary_key
    assert column.server_default is None
    assert column.default.arg.__name__ == uuid.uuid4.__name__
    assert_no_server_default_primary_keys(ModuleBase.metadata)


def test_server_default_primary_key_is_named() -> None:
    clean, dirty = MetaData(), MetaData()
    Table("ok", clean, Column("id", Integer, primary_key=True))
    Table(
        "legacy",
        dirty,
        Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
        ),
        schema="tasks",
    )

    with pytest.raises(AssertionError, match=r"tasks\.legacy\.id"):
        assert_no_server_default_primary_keys(clean, dirty)
