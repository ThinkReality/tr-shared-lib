"""Tests for monitoring Celery tasks (using direct function calls, no broker)."""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tr_shared.monitoring.tasks import (
    _batch_insert_records,
    _create_sync_engine,
    _ensure_partition,
    _get_sync_redis,
    aggregate_daily_metrics,
    aggregate_hourly_metrics,
    cleanup_old_monitoring_logs,
    create_next_day_partition,
    flush_monitoring_buffer,
)


class TestCreateSyncEngine:
    def test_converts_asyncpg_url_to_sync(self):
        with patch("sqlalchemy.create_engine") as mock_engine:
            _create_sync_engine("postgresql+asyncpg://user:pass@host/db")
            url = mock_engine.call_args[0][0]
            assert "asyncpg" not in url
            assert url.startswith("postgresql://")

    def test_converts_postgres_shorthand(self):
        with patch("sqlalchemy.create_engine") as mock_engine:
            _create_sync_engine("postgres://user:pass@host/db")
            url = mock_engine.call_args[0][0]
            assert url.startswith("postgresql://")

    def test_plain_postgresql_url_unchanged(self):
        with patch("sqlalchemy.create_engine") as mock_engine:
            _create_sync_engine("postgresql://user:pass@host/db")
            url = mock_engine.call_args[0][0]
            assert url == "postgresql://user:pass@host/db"

    def test_uses_null_pool(self):
        from sqlalchemy.pool import NullPool

        with patch("sqlalchemy.create_engine") as mock_engine:
            _create_sync_engine("postgresql://user:pass@host/db")
            assert mock_engine.call_args[1]["poolclass"] is NullPool


class TestGetSyncRedis:
    def test_calls_from_url_with_decode_responses(self):
        with patch("redis.Redis.from_url") as mock_from_url:
            _get_sync_redis("redis://localhost:6379/0")
            mock_from_url.assert_called_once_with(
                "redis://localhost:6379/0", decode_responses=True
            )


class TestEnsurePartition:
    def test_executes_create_table_statement(self):
        engine = MagicMock()
        _ensure_partition(engine, date(2026, 3, 1))
        engine.begin.assert_called_once()

    def test_swallows_partition_exists_error(self):
        engine = MagicMock()
        engine.begin.side_effect = Exception("partition already exists")
        _ensure_partition(engine, date.today())  # Must not raise

    def test_partition_name_uses_target_date(self):
        engine = MagicMock()
        conn = engine.begin.return_value.__enter__.return_value
        _ensure_partition(engine, date(2026, 3, 15))
        # The SQL text should reference the partition name
        sql_str = str(conn.execute.call_args[0][0])
        assert "2026_03_15" in sql_str


class TestBatchInsertRecords:
    def test_calls_ensure_partition(self):
        engine = MagicMock()
        with patch("tr_shared.monitoring.tasks._helpers._ensure_partition") as mock_ep:
            _batch_insert_records(engine, [{"service_name": "svc", "status_code": 200}])
            mock_ep.assert_called_once()

    def test_executes_insert_for_each_record(self):
        engine = MagicMock()
        conn = engine.begin.return_value.__enter__.return_value
        with patch("tr_shared.monitoring.tasks._helpers._ensure_partition"):
            _batch_insert_records(engine, [
                {"service_name": "s", "status_code": 200, "response_time_ms": 10},
                {"service_name": "s", "status_code": 404, "response_time_ms": 5},
            ])
        assert conn.execute.call_count == 2

    def test_skips_bad_record_without_raising(self):
        engine = MagicMock()
        conn = engine.begin.return_value.__enter__.return_value
        conn.execute.side_effect = [Exception("insert failed"), None]
        with patch("tr_shared.monitoring.tasks._helpers._ensure_partition"):
            # Should not raise even when first insert fails
            _batch_insert_records(engine, [
                {"status_code": 200},
                {"status_code": 404},
            ])


class TestFlushMonitoringBuffer:
    def test_flushes_records_and_inserts(self):
        with patch("tr_shared.monitoring.tasks.buffer._create_sync_engine") as mock_eng_fn, \
             patch("tr_shared.monitoring.tasks.buffer._get_sync_redis") as mock_redis_fn, \
             patch("tr_shared.monitoring.redis_buffer.flush_buffer_sync") as mock_flush, \
             patch("tr_shared.monitoring.tasks.buffer._batch_insert_records") as mock_insert:

            mock_eng_fn.return_value = MagicMock()
            mock_redis_fn.return_value = MagicMock()
            mock_flush.side_effect = [
                [{"service_name": "svc", "status_code": 200}],
                [],
            ]
            flush_monitoring_buffer("svc", "postgresql://...", "redis://...")
            mock_insert.assert_called_once()

    def test_disposes_engine_after_flush(self):
        with patch("tr_shared.monitoring.tasks.buffer._create_sync_engine") as mock_eng_fn, \
             patch("tr_shared.monitoring.tasks.buffer._get_sync_redis"), \
             patch("tr_shared.monitoring.redis_buffer.flush_buffer_sync", return_value=[]):

            mock_engine = MagicMock()
            mock_eng_fn.return_value = mock_engine
            flush_monitoring_buffer("svc", "postgresql://...", "redis://...")
            mock_engine.dispose.assert_called_once()

    def test_handles_flush_error_gracefully(self):
        """Exceptions inside the flush loop are caught and logged."""
        with patch("tr_shared.monitoring.tasks.buffer._create_sync_engine") as mock_eng_fn, \
             patch("tr_shared.monitoring.tasks.buffer._get_sync_redis"), \
             patch("tr_shared.monitoring.redis_buffer.flush_buffer_sync") as mock_flush:

            mock_engine = MagicMock()
            mock_eng_fn.return_value = mock_engine
            mock_flush.side_effect = Exception("flush error")
            flush_monitoring_buffer("svc", "postgresql://...", "redis://...")  # Must not raise
            mock_engine.dispose.assert_called_once()

    def test_stops_loop_when_buffer_empty(self):
        with patch("tr_shared.monitoring.tasks.buffer._create_sync_engine") as mock_eng_fn, \
             patch("tr_shared.monitoring.tasks.buffer._get_sync_redis"), \
             patch("tr_shared.monitoring.redis_buffer.flush_buffer_sync", return_value=[]) as mock_flush, \
             patch("tr_shared.monitoring.tasks.buffer._batch_insert_records") as mock_insert:

            mock_eng_fn.return_value = MagicMock()
            flush_monitoring_buffer("svc", "postgresql://...", "redis://...")
            mock_insert.assert_not_called()


class TestAggregateHourlyMetrics:
    def test_executes_queries_and_disposes(self):
        with patch("tr_shared.monitoring.tasks.aggregation._create_sync_engine") as mock_eng_fn:
            mock_engine = MagicMock()
            mock_eng_fn.return_value = mock_engine
            aggregate_hourly_metrics("postgresql://...")
            mock_engine.dispose.assert_called_once()

    def test_handles_db_error_gracefully(self):
        with patch("tr_shared.monitoring.tasks.aggregation._create_sync_engine") as mock_eng_fn:
            mock_engine = MagicMock()
            mock_engine.begin.side_effect = Exception("db error")
            mock_eng_fn.return_value = mock_engine
            aggregate_hourly_metrics("postgresql://...")  # Must not raise
            mock_engine.dispose.assert_called_once()


class TestAggregateDailyMetrics:
    def test_executes_and_disposes_engine(self):
        with patch("tr_shared.monitoring.tasks.aggregation._create_sync_engine") as mock_eng_fn:
            mock_engine = MagicMock()
            mock_eng_fn.return_value = mock_engine
            aggregate_daily_metrics("postgresql://...")
            mock_engine.dispose.assert_called_once()

    def test_handles_db_error(self):
        with patch("tr_shared.monitoring.tasks.aggregation._create_sync_engine") as mock_eng_fn:
            mock_engine = MagicMock()
            mock_engine.begin.side_effect = Exception("db error")
            mock_eng_fn.return_value = mock_engine
            aggregate_daily_metrics("postgresql://...")
            mock_engine.dispose.assert_called_once()


class TestCreateNextDayPartition:
    def test_creates_tomorrows_partition(self):
        with patch("tr_shared.monitoring.tasks.maintenance._create_sync_engine") as mock_eng_fn, \
             patch("tr_shared.monitoring.tasks.maintenance._ensure_partition") as mock_part:

            mock_eng_fn.return_value = MagicMock()
            create_next_day_partition("postgresql://...")
            mock_part.assert_called_once()
            _, partition_date = mock_part.call_args[0]
            assert partition_date == date.today() + timedelta(days=1)

    def test_disposes_engine(self):
        with patch("tr_shared.monitoring.tasks.maintenance._create_sync_engine") as mock_eng_fn, \
             patch("tr_shared.monitoring.tasks.maintenance._ensure_partition"):

            mock_engine = MagicMock()
            mock_eng_fn.return_value = mock_engine
            create_next_day_partition("postgresql://...")
            mock_engine.dispose.assert_called_once()


class TestCleanupOldMonitoringLogs:
    def test_drops_old_partitions(self):
        with patch("tr_shared.monitoring.tasks.maintenance._create_sync_engine") as mock_eng_fn:
            mock_engine = MagicMock()
            conn = mock_engine.begin.return_value.__enter__.return_value
            old_date = date.today() - timedelta(days=100)
            partition_name = f"request_logs_{old_date.strftime('%Y_%m_%d')}"
            conn.execute.return_value.fetchall.return_value = [(partition_name,)]
            mock_eng_fn.return_value = mock_engine

            cleanup_old_monitoring_logs("postgresql://...", retention_days=90)
            # Should have executed find + drop statements
            assert conn.execute.call_count >= 2

    def test_skips_recent_partitions(self):
        with patch("tr_shared.monitoring.tasks.maintenance._create_sync_engine") as mock_eng_fn:
            mock_engine = MagicMock()
            conn = mock_engine.begin.return_value.__enter__.return_value
            recent = date.today() - timedelta(days=5)
            partition_name = f"request_logs_{recent.strftime('%Y_%m_%d')}"
            conn.execute.return_value.fetchall.return_value = [(partition_name,)]
            mock_eng_fn.return_value = mock_engine

            cleanup_old_monitoring_logs("postgresql://...", retention_days=90)
            # Only one execute call (the find query) — no DROP
            assert conn.execute.call_count == 1

    def test_handles_db_error(self):
        with patch("tr_shared.monitoring.tasks.maintenance._create_sync_engine") as mock_eng_fn:
            mock_engine = MagicMock()
            mock_engine.begin.side_effect = Exception("db error")
            mock_eng_fn.return_value = mock_engine
            cleanup_old_monitoring_logs("postgresql://...")  # Must not raise
            mock_engine.dispose.assert_called_once()
