"""Tests for tr_shared.db.migrations.dedup."""

from unittest.mock import MagicMock

import pytest

from tr_shared.db.migrations import dedup_with_table_lock


def _emitted_sql(op: MagicMock) -> list[str]:
    return [call[0][0] for call in op.execute.call_args_list]


class TestDedupWithTableLock:
    def test_emits_lock_before_dedup(self):
        op = MagicMock()
        dedup_with_table_lock(
            op,
            table="platform_configs",
            schema="admin",
            partition_by=["tenant_id", "platform_name"],
            order_by=["is_enabled DESC", "updated_at DESC NULLS LAST"],
        )
        sqls = _emitted_sql(op)
        # 3 statements: LOCK, RAISE NOTICE DO-block, UPDATE
        assert len(sqls) == 3
        assert "LOCK TABLE" in sqls[0]
        assert "SHARE ROW EXCLUSIVE" in sqls[0]
        assert '"admin"."platform_configs"' in sqls[0]

    def test_soft_delete_sets_default_columns(self):
        op = MagicMock()
        dedup_with_table_lock(
            op,
            table="t",
            schema="s",
            partition_by=["tenant_id"],
            order_by=["created_at DESC"],
        )
        update_sql = _emitted_sql(op)[2]
        assert "UPDATE" in update_sql
        assert '"deleted_at" = NOW()' in update_sql
        assert '"is_enabled" = FALSE' in update_sql
        assert '"is_active" = FALSE' in update_sql

    def test_custom_soft_delete_columns(self):
        op = MagicMock()
        dedup_with_table_lock(
            op,
            table="t",
            schema="s",
            partition_by=["x"],
            order_by=["y"],
            soft_delete_columns={"archived_at": "NOW()"},
        )
        update_sql = _emitted_sql(op)[2]
        assert '"archived_at" = NOW()' in update_sql
        assert "deleted_at" not in update_sql

    def test_hard_delete_uses_delete_from(self):
        op = MagicMock()
        dedup_with_table_lock(
            op,
            table="t",
            schema="s",
            partition_by=["x"],
            order_by=["y"],
            strategy="hard_delete",
        )
        action_sql = _emitted_sql(op)[2]
        assert "DELETE FROM" in action_sql

    def test_unknown_strategy_raises(self):
        op = MagicMock()
        with pytest.raises(ValueError, match="Unknown dedup strategy"):
            dedup_with_table_lock(
                op,
                table="t",
                schema="s",
                partition_by=["x"],
                order_by=["y"],
                strategy="frobnicate",  # type: ignore[arg-type]
            )

    def test_filter_predicate_injected_as_where(self):
        op = MagicMock()
        dedup_with_table_lock(
            op,
            table="t",
            schema="s",
            partition_by=["x"],
            order_by=["y"],
            filter_predicate="platform_name = 'PropertyFinder API'",
        )
        notice_sql = _emitted_sql(op)[1]
        update_sql = _emitted_sql(op)[2]
        assert "WHERE platform_name = 'PropertyFinder API'" in notice_sql
        assert "WHERE platform_name = 'PropertyFinder API'" in update_sql

    def test_partition_and_order_preserved(self):
        op = MagicMock()
        dedup_with_table_lock(
            op,
            table="t",
            schema="s",
            partition_by=["a", "b"],
            order_by=["c DESC", "d ASC NULLS LAST"],
        )
        update_sql = _emitted_sql(op)[2]
        assert 'PARTITION BY "a", "b"' in update_sql
        assert "ORDER BY c DESC, d ASC NULLS LAST" in update_sql
