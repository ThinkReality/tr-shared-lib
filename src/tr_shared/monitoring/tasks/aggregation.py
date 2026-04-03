"""
Metrics aggregation tasks — roll up request_logs into hourly and daily summaries.
"""

import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task

from tr_shared.monitoring.tasks._helpers import _create_sync_engine

logger = logging.getLogger(__name__)


@shared_task(name="monitoring.aggregate_hourly", ignore_result=True)
def aggregate_hourly_metrics(monitoring_db_url: str) -> None:
    """
    Aggregate request_logs into metrics_hourly for the previous hour.

    Also updates tenant_usage for the current day.
    Runs at :05 past every hour.
    """
    from sqlalchemy import text

    engine = _create_sync_engine(monitoring_db_url)

    try:
        now = datetime.now(timezone.utc)
        prev_hour = now - timedelta(hours=1)
        target_date = prev_hour.date()
        target_hour = prev_hour.hour

        hourly_sql = text("""
            INSERT INTO monitoring.metrics_hourly (
                id, service_name, date, hour, endpoint, tenant_id,
                request_count, error_count, error_rate_percent,
                avg_response_time_ms, min_response_time_ms, max_response_time_ms,
                p95_response_time_ms, p99_response_time_ms,
                total_request_size_bytes, total_response_size_bytes,
                created_at
            )
            SELECT
                gen_random_uuid(),
                service_name,
                date,
                hour,
                endpoint,
                tenant_id,
                COUNT(*) as request_count,
                COUNT(*) FILTER (WHERE status_code >= 400) as error_count,
                ROUND(100.0 * COUNT(*) FILTER (WHERE status_code >= 400) / NULLIF(COUNT(*), 0), 2),
                ROUND(AVG(response_time_ms)::numeric, 2),
                MIN(response_time_ms),
                MAX(response_time_ms),
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms)::int,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY response_time_ms)::int,
                SUM(request_size_bytes),
                SUM(response_size_bytes),
                NOW()
            FROM monitoring.request_logs
            WHERE date = :target_date AND hour = :target_hour
            GROUP BY service_name, date, hour, endpoint, tenant_id
            ON CONFLICT (service_name, date, hour, endpoint, tenant_id)
            DO UPDATE SET
                request_count = EXCLUDED.request_count,
                error_count = EXCLUDED.error_count,
                error_rate_percent = EXCLUDED.error_rate_percent,
                avg_response_time_ms = EXCLUDED.avg_response_time_ms,
                min_response_time_ms = EXCLUDED.min_response_time_ms,
                max_response_time_ms = EXCLUDED.max_response_time_ms,
                p95_response_time_ms = EXCLUDED.p95_response_time_ms,
                p99_response_time_ms = EXCLUDED.p99_response_time_ms,
                total_request_size_bytes = EXCLUDED.total_request_size_bytes,
                total_response_size_bytes = EXCLUDED.total_response_size_bytes
        """)

        tenant_sql = text("""
            INSERT INTO monitoring.tenant_usage (
                id, service_name, tenant_id, date,
                total_requests, total_errors, error_rate_percent,
                avg_response_time_ms, total_request_bytes, total_response_bytes,
                created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                service_name,
                tenant_id,
                date,
                COUNT(*),
                COUNT(*) FILTER (WHERE status_code >= 400),
                ROUND(100.0 * COUNT(*) FILTER (WHERE status_code >= 400) / NULLIF(COUNT(*), 0), 2),
                ROUND(AVG(response_time_ms)::numeric, 2),
                SUM(request_size_bytes),
                SUM(response_size_bytes),
                NOW(),
                NOW()
            FROM monitoring.request_logs
            WHERE date = :target_date AND hour = :target_hour
              AND tenant_id IS NOT NULL
            GROUP BY service_name, tenant_id, date
            ON CONFLICT (service_name, tenant_id, date)
            DO UPDATE SET
                total_requests = monitoring.tenant_usage.total_requests + EXCLUDED.total_requests,
                total_errors = monitoring.tenant_usage.total_errors + EXCLUDED.total_errors,
                error_rate_percent = ROUND(
                    100.0 * (monitoring.tenant_usage.total_errors + EXCLUDED.total_errors)
                    / NULLIF(monitoring.tenant_usage.total_requests + EXCLUDED.total_requests, 0), 2
                ),
                avg_response_time_ms = EXCLUDED.avg_response_time_ms,
                total_request_bytes = COALESCE(monitoring.tenant_usage.total_request_bytes, 0) + COALESCE(EXCLUDED.total_request_bytes, 0),
                total_response_bytes = COALESCE(monitoring.tenant_usage.total_response_bytes, 0) + COALESCE(EXCLUDED.total_response_bytes, 0),
                updated_at = NOW()
        """)

        with engine.begin() as conn:
            conn.execute(hourly_sql, {"target_date": target_date, "target_hour": target_hour})
            conn.execute(tenant_sql, {"target_date": target_date, "target_hour": target_hour})

        logger.info(
            "Aggregated hourly metrics for %s hour %d",
            target_date, target_hour,
        )
    except Exception as exc:
        logger.error("aggregate_hourly_metrics failed: %s", exc)
    finally:
        engine.dispose()


@shared_task(name="monitoring.aggregate_daily", ignore_result=True)
def aggregate_daily_metrics(monitoring_db_url: str) -> None:
    """
    Aggregate metrics_hourly into metrics_daily for the previous day.
    Runs daily at 01:00.
    """
    from datetime import date
    from sqlalchemy import text

    engine = _create_sync_engine(monitoring_db_url)

    try:
        yesterday = date.today() - timedelta(days=1)

        daily_sql = text("""
            INSERT INTO monitoring.metrics_daily (
                id, service_name, date, endpoint, tenant_id,
                request_count, error_count, error_rate_percent,
                avg_requests_per_hour, avg_response_time_ms,
                p95_response_time_ms, p99_response_time_ms,
                created_at
            )
            SELECT
                gen_random_uuid(),
                service_name,
                date,
                endpoint,
                tenant_id,
                SUM(request_count),
                SUM(error_count),
                ROUND(100.0 * SUM(error_count) / NULLIF(SUM(request_count), 0), 2),
                ROUND(SUM(request_count)::numeric / 24, 2),
                ROUND(AVG(avg_response_time_ms), 2),
                MAX(p95_response_time_ms),
                MAX(p99_response_time_ms),
                NOW()
            FROM monitoring.metrics_hourly
            WHERE date = :yesterday
            GROUP BY service_name, date, endpoint, tenant_id
            ON CONFLICT (service_name, date, endpoint, tenant_id)
            DO UPDATE SET
                request_count = EXCLUDED.request_count,
                error_count = EXCLUDED.error_count,
                error_rate_percent = EXCLUDED.error_rate_percent,
                avg_requests_per_hour = EXCLUDED.avg_requests_per_hour,
                avg_response_time_ms = EXCLUDED.avg_response_time_ms,
                p95_response_time_ms = EXCLUDED.p95_response_time_ms,
                p99_response_time_ms = EXCLUDED.p99_response_time_ms
        """)

        with engine.begin() as conn:
            conn.execute(daily_sql, {"yesterday": yesterday})

        logger.info("Aggregated daily metrics for %s", yesterday)
    except Exception as exc:
        logger.error("aggregate_daily_metrics failed: %s", exc)
    finally:
        engine.dispose()
