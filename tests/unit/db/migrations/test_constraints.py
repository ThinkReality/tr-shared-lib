"""Tests for tr_shared.db.migrations.constraints."""

from unittest.mock import MagicMock

import pytest

from tr_shared.db.migrations import (
    CrossSchemaFKError,
    add_check_constraint_deferred,
    add_fk_deferred,
)


class TestAddCheckConstraintDeferred:
    def test_emits_not_valid_then_validate(self):
        op = MagicMock()
        add_check_constraint_deferred(
            op,
            table="platform_configs",
            schema="admin",
            constraint_name="ck_platform_name_known",
            predicate="platform_name IN ('A', 'B')",
        )
        assert op.execute.call_count == 2

        first_sql = op.execute.call_args_list[0][0][0]
        assert "NOT VALID" in first_sql
        assert "ck_platform_name_known" in first_sql
        assert "admin" in first_sql
        assert "platform_configs" in first_sql
        assert "platform_name IN ('A', 'B')" in first_sql

        second_sql = op.execute.call_args_list[1][0][0]
        assert "VALIDATE CONSTRAINT" in second_sql
        assert "ck_platform_name_known" in second_sql

    def test_quotes_embedded_double_quote_in_constraint_name(self):
        op = MagicMock()
        add_check_constraint_deferred(
            op,
            table="t",
            schema="s",
            constraint_name='weird"name',
            predicate="x > 0",
        )
        first_sql = op.execute.call_args_list[0][0][0]
        # Quoted identifier doubles embedded double-quotes.
        assert '"weird""name"' in first_sql


class TestAddFKDeferred:
    def test_same_schema_succeeds(self):
        op = MagicMock()
        add_fk_deferred(
            op,
            table="child",
            schema="admin",
            constraint_name="fk_child_parent",
            columns=["parent_id"],
            ref_table="parent",
            ref_schema="admin",
            ref_columns=["id"],
            on_delete="CASCADE",
        )
        assert op.execute.call_count == 2
        first_sql = op.execute.call_args_list[0][0][0]
        assert "FOREIGN KEY" in first_sql
        assert "REFERENCES" in first_sql
        assert "ON DELETE CASCADE" in first_sql
        assert "NOT VALID" in first_sql

        second_sql = op.execute.call_args_list[1][0][0]
        assert "VALIDATE CONSTRAINT" in second_sql

    def test_cross_schema_raises(self):
        op = MagicMock()
        with pytest.raises(CrossSchemaFKError) as excinfo:
            add_fk_deferred(
                op,
                table="child",
                schema="admin",
                constraint_name="fk_child_tenant",
                columns=["tenant_id"],
                ref_table="auth_tenant",
                ref_schema="public",
                ref_columns=["id"],
            )
        msg = str(excinfo.value)
        assert "admin.child" in msg
        assert "public.auth_tenant" in msg
        assert "crosses service schemas" in msg.lower()
        # No SQL should have been emitted.
        op.execute.assert_not_called()

    def test_without_on_delete_omits_clause(self):
        op = MagicMock()
        add_fk_deferred(
            op,
            table="child",
            schema="admin",
            constraint_name="fk",
            columns=["parent_id"],
            ref_table="parent",
            ref_schema="admin",
            ref_columns=["id"],
        )
        first_sql = op.execute.call_args_list[0][0][0]
        assert "ON DELETE" not in first_sql

    def test_cross_schema_error_is_value_error(self):
        # Type invariant so callers can catch ValueError generically if needed.
        assert issubclass(CrossSchemaFKError, ValueError)
