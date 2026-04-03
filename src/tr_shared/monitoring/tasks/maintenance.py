"""
Infrastructure maintenance tasks — partition management and log retention.
"""

import logging
from datetime import date, timedelta

from celery import shared_task

from tr_shared.monitoring.tasks._helpers import _create_sync_engine, _ensure_partition

logger = logging.getLogger(__name__)


@shared_task(name="monitoring.create_partition", ignore_result=True)
def create_next_day_partition(monitoring_db_url: str) -> None:
    """
    Create tomorrow's partition for monitoring.request_logs.
    Runs daily at 23:55.
    """
    engine = _create_sync_engine(monitoring_db_url)
    try:
        tomorrow = date.today() + timedelta(days=1)
        _ensure_partition(engine, tomorrow)
        logger.info("Created partition for %s", tomorrow)
    except Exception as exc:
        logger.error("create_next_day_partition failed: %s", exc)
    finally:
        engine.dispose()


@shared_task(name="monitoring.cleanup_old_logs", ignore_result=True)
def cleanup_old_monitoring_logs(
    monitoring_db_url: str,
    retention_days: int = 90,
) -> None:
    """
    Drop request_logs partitions older than *retention_days*.
    Runs daily at 02:00.
    """
    from sqlalchemy import text

    engine = _create_sync_engine(monitoring_db_url)

    try:
        cutoff = date.today() - timedelta(days=retention_days)

        find_sql = text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'monitoring'
              AND tablename LIKE 'request_logs_%'
        """)

        with engine.begin() as conn:
            rows = conn.execute(find_sql).fetchall()
            dropped = 0
            for (tablename,) in rows:
                # Extract date from partition name: request_logs_2026_03_01
                parts = tablename.replace("request_logs_", "").split("_")
                if len(parts) == 3:
                    try:
                        partition_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                        if partition_date < cutoff:
                            conn.execute(text(
                                f"DROP TABLE IF EXISTS monitoring.{tablename}"
                            ))
                            dropped += 1
                    except (ValueError, IndexError):
                        continue

            if dropped:
                logger.info(
                    "Dropped %d old monitoring partitions (cutoff: %s)",
                    dropped, cutoff,
                )
    except Exception as exc:
        logger.error("cleanup_old_monitoring_logs failed: %s", exc)
    finally:
        engine.dispose()
