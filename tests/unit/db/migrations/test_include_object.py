"""Tests for tr_shared.db.migrations.include_object."""

from types import SimpleNamespace

from sqlalchemy import Column, Integer, MetaData, Table

from tr_shared.db.migrations import (
    make_service_include_name,
    make_service_include_object,
)


def _build_metadata() -> MetaData:
    md = MetaData()
    Table("foo", md, Column("id", Integer, primary_key=True), schema="admin")
    Table("bar", md, Column("id", Integer, primary_key=True), schema="admin")
    # Also add a rogue table in public to prove the filter rejects it.
    Table("leaks", md, Column("id", Integer, primary_key=True), schema="public")
    return md


class TestMakeServiceIncludeObject:
    def test_table_in_target_schema_and_metadata_included(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        obj = SimpleNamespace(schema="admin")
        assert inc(obj, "foo", "table", False, None) is True

    def test_table_in_target_schema_but_not_metadata_excluded(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        obj = SimpleNamespace(schema="admin")
        assert inc(obj, "strange_orphan", "table", False, None) is False

    def test_table_in_other_schema_excluded(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        obj = SimpleNamespace(schema="public")
        assert inc(obj, "foo", "table", False, None) is False

    def test_index_on_own_table_included(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        parent = SimpleNamespace(name="foo", schema="admin")
        obj = SimpleNamespace(table=parent)
        assert inc(obj, "ix_foo_bar", "index", False, None) is True

    def test_index_on_foreign_table_excluded(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        parent = SimpleNamespace(name="foo", schema="public")
        obj = SimpleNamespace(table=parent)
        assert inc(obj, "ix_public_foo", "index", False, None) is False

    def test_check_constraint_on_foreign_table_excluded(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        parent = SimpleNamespace(name="users", schema="auth_schema")
        obj = SimpleNamespace(table=parent)
        assert inc(obj, "ck_auth_users_active", "check_constraint", False, None) is False

    def test_sequence_in_target_schema_included(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        obj = SimpleNamespace(schema="admin")
        # Custom type_ name should still be resolved via obj.schema fallback
        # because SimpleNamespace has no .table attribute.
        assert inc(obj, "some_seq", "sequence", False, None) is True

    def test_sequence_in_foreign_schema_excluded(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        obj = SimpleNamespace(schema="public")
        assert inc(obj, "some_seq", "sequence", False, None) is False

    def test_unknown_object_with_no_schema_passes_through(self):
        md = _build_metadata()
        inc = make_service_include_object("admin", md)
        # No .schema, no .table — helper lets Alembic decide.
        obj = SimpleNamespace()
        assert inc(obj, "???", "mystery", False, None) is True


class TestMakeServiceIncludeName:
    def test_own_schema_reflected(self):
        inc = make_service_include_name("admin")
        assert inc("admin", "schema", {}) is True

    def test_foreign_schema_rejected(self):
        inc = make_service_include_name("admin")
        assert inc("hr", "schema", {}) is False
        assert inc("lead", "schema", {}) is False

    def test_default_schema_rejected_when_not_allowed(self):
        inc = make_service_include_name("admin")
        assert inc(None, "schema", {}) is False

    def test_variadic_allow_list_for_auth(self):
        # auth manages auth_schema plus two public tables → default + public allowed.
        inc = make_service_include_name(None, "public", "auth_schema")
        assert inc("auth_schema", "schema", {}) is True
        assert inc("public", "schema", {}) is True
        assert inc(None, "schema", {}) is True
        assert inc("hr", "schema", {}) is False

    def test_non_schema_type_passes_through(self):
        inc = make_service_include_name("admin")
        # Table/index/etc. names are gated by include_object, not include_name.
        assert inc("foreign_table", "table", {}) is True
        assert inc("some_index", "index", {}) is True
