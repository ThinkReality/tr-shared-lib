"""Tests for BaseModel mixins and soft-delete/restore helpers."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect

from tr_shared.db.base import (
    AuditMixin,
    Base,
    BaseModel,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SampleModel(BaseModel):
    """Minimal concrete model for testing BaseModel methods."""
    __tablename__ = "test_sample_model"


# ---------------------------------------------------------------------------
# TimestampMixin column definitions
# ---------------------------------------------------------------------------

class TestTimestampMixin:
    def test_created_at_column_exists(self):
        assert hasattr(TimestampMixin, "created_at")

    def test_updated_at_column_exists(self):
        assert hasattr(TimestampMixin, "updated_at")

    def test_created_at_not_nullable(self):
        col = TimestampMixin.__dict__["created_at"]
        assert col.nullable is False

    def test_updated_at_is_nullable(self):
        col = TimestampMixin.__dict__["updated_at"]
        assert col.nullable is False


# ---------------------------------------------------------------------------
# TenantMixin column definitions
# ---------------------------------------------------------------------------

class TestTenantMixin:
    def test_tenant_id_column_exists(self):
        assert hasattr(TenantMixin, "tenant_id")

    def test_tenant_id_not_nullable(self):
        col = TenantMixin.__dict__["tenant_id"]
        assert col.nullable is False

    def test_tenant_id_is_indexed(self):
        col = TenantMixin.__dict__["tenant_id"]
        assert col.index is True


# ---------------------------------------------------------------------------
# AuditMixin column definitions
# ---------------------------------------------------------------------------

class TestAuditMixin:
    def test_created_by_column_exists(self):
        assert hasattr(AuditMixin, "created_by")

    def test_updated_by_column_exists(self):
        assert hasattr(AuditMixin, "updated_by")

    def test_created_by_is_nullable(self):
        col = AuditMixin.__dict__["created_by"]
        assert col.nullable is True

    def test_updated_by_is_nullable(self):
        col = AuditMixin.__dict__["updated_by"]
        assert col.nullable is True


# ---------------------------------------------------------------------------
# SoftDeleteMixin column definitions
# ---------------------------------------------------------------------------

class TestSoftDeleteMixin:
    def test_deleted_at_column_exists(self):
        assert hasattr(SoftDeleteMixin, "deleted_at")

    def test_is_active_column_exists(self):
        assert hasattr(SoftDeleteMixin, "is_active")

    def test_deleted_at_is_nullable(self):
        col = SoftDeleteMixin.__dict__["deleted_at"]
        assert col.nullable is True

    def test_is_active_not_nullable(self):
        col = SoftDeleteMixin.__dict__["is_active"]
        assert col.nullable is False


# ---------------------------------------------------------------------------
# BaseModel.soft_delete()
# ---------------------------------------------------------------------------

class TestSoftDelete:
    def test_soft_delete_sets_is_active_false(self):
        model = SampleModel()
        model.soft_delete()
        assert model.is_active is False

    def test_soft_delete_sets_deleted_at(self):
        model = SampleModel()
        model.soft_delete()
        assert model.deleted_at is not None

    def test_soft_delete_deleted_at_is_recent(self):
        model = SampleModel()
        before = datetime.now(timezone.utc)
        model.soft_delete()
        assert model.deleted_at >= before

    def test_soft_delete_deleted_at_is_timezone_aware(self):
        model = SampleModel()
        model.soft_delete()
        assert model.deleted_at.tzinfo is not None


# ---------------------------------------------------------------------------
# BaseModel.restore()
# ---------------------------------------------------------------------------

class TestRestore:
    def test_restore_sets_is_active_true(self):
        model = SampleModel()
        model.soft_delete()
        model.restore()
        assert model.is_active is True

    def test_restore_clears_deleted_at(self):
        model = SampleModel()
        model.soft_delete()
        model.restore()
        assert model.deleted_at is None

    def test_restore_on_non_deleted_model_is_safe(self):
        model = SampleModel()
        model.restore()  # Should not raise
        assert model.is_active is True
        assert model.deleted_at is None


# ---------------------------------------------------------------------------
# BaseModel.__repr__
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_contains_class_name(self):
        model = SampleModel()
        assert "SampleModel" in repr(model)

    def test_repr_contains_id(self):
        model = SampleModel()
        model.id = uuid.uuid4()
        r = repr(model)
        assert str(model.id) in r

    def test_repr_format(self):
        model = SampleModel()
        model.id = None
        r = repr(model)
        assert r.startswith("<SampleModel(id=")


# ---------------------------------------------------------------------------
# BaseModel is abstract
# ---------------------------------------------------------------------------

class TestBaseModelAbstract:
    def test_base_model_is_abstract(self):
        # BaseModel declares __abstract__ = True; SampleModel inherits it
        assert BaseModel.__abstract__ is True

    def test_sample_model_inherits_all_mixins(self):
        attrs = dir(SampleModel)
        for attr in ["id", "tenant_id", "created_at", "updated_at", "deleted_at",
                     "is_active", "created_by", "updated_by"]:
            assert attr in attrs, f"Expected {attr} in SampleModel"
