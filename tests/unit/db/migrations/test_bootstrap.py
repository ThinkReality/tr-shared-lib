"""Tests for tr_shared.db.migrations.bootstrap."""


from tr_shared.db.migrations import (
    UNDELIVERED_EVENTS_COLUMNS,
    bootstrap_schema_and_version_table,
)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConnection:
    """Minimal fake that records executes and drives scalar() per-call."""

    def __init__(self, scalar_results: list):
        self._scalar_results = list(scalar_results)
        self.executed: list[str] = []
        self.commit_count = 0

    def execute(self, stmt, params=None):
        # stmt is a sqlalchemy.text() object; record its str() form.
        self.executed.append((str(stmt), params))
        if "information_schema.tables" in str(stmt):
            # Pop next scalar value.
            return _FakeResult(self._scalar_results.pop(0))
        return _FakeResult(None)

    def commit(self):
        self.commit_count += 1


class TestBootstrapSchemaAndVersionTable:
    def test_first_ever_run_returns_absent(self):
        conn = _FakeConnection(scalar_results=[None, None])
        result = bootstrap_schema_and_version_table(
            conn,
            schema="admin",
            version_table="alembic_version_admin_panel",
        )
        assert result == "absent"
        # CREATE SCHEMA was emitted first.
        assert "CREATE SCHEMA IF NOT EXISTS" in conn.executed[0][0]
        assert '"admin"' in conn.executed[0][0]
        assert conn.commit_count == 1

    def test_version_table_already_in_target(self):
        # Helper probes both target and legacy; target=1 short-circuits behavior
        # but both queries still execute.
        conn = _FakeConnection(scalar_results=[1, None])
        result = bootstrap_schema_and_version_table(
            conn,
            schema="admin",
            version_table="alembic_version_admin_panel",
        )
        assert result == "target"
        # Should NOT have emitted ALTER TABLE SET SCHEMA.
        altered = [s for s, _ in conn.executed if "SET SCHEMA" in s]
        assert altered == []

    def test_version_table_in_legacy_is_moved(self):
        conn = _FakeConnection(scalar_results=[None, 1])  # not target, yes legacy
        result = bootstrap_schema_and_version_table(
            conn,
            schema="admin",
            version_table="alembic_version_admin_panel",
        )
        assert result == "target"
        altered = [s for s, _ in conn.executed if "SET SCHEMA" in s]
        assert len(altered) == 1
        assert '"public"."alembic_version_admin_panel"' in altered[0]
        assert 'SET SCHEMA "admin"' in altered[0]

    def test_custom_legacy_schema(self):
        conn = _FakeConnection(scalar_results=[None, 1])
        result = bootstrap_schema_and_version_table(
            conn,
            schema="admin",
            version_table="alembic_version_admin_panel",
            legacy_schema="old_admin",
        )
        assert result == "target"
        altered = [s for s, _ in conn.executed if "SET SCHEMA" in s]
        assert '"old_admin"."alembic_version_admin_panel"' in altered[0]

    def test_commits_bootstrap_transaction(self):
        conn = _FakeConnection(scalar_results=[1, None])
        bootstrap_schema_and_version_table(
            conn, schema="admin", version_table="v",
        )
        assert conn.commit_count == 1


class TestUndeliveredEventsColumns:
    def test_contains_required_columns(self):
        required = [
            "id UUID PRIMARY KEY",
            "event_type TEXT NOT NULL",
            "tenant_id UUID NOT NULL",
            "data JSONB NOT NULL",
            "retry_count INT NOT NULL",
            "dead_letter BOOLEAN NOT NULL",
            "next_retry_at TIMESTAMPTZ NOT NULL",
        ]
        for col in required:
            assert col in UNDELIVERED_EVENTS_COLUMNS, f"missing: {col}"
