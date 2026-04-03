"""
Internal helpers shared across monitoring task modules.

Not part of the public API — import from tr_shared.monitoring.tasks instead.
"""

import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _create_sync_engine(db_url: str):
    """Create a short-lived sync engine for use in Celery tasks."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    # Convert async URL to sync if needed
    url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgres://", "postgresql://")

    return create_engine(url, poolclass=NullPool)


def _get_sync_redis(redis_url: str):
    """Create a synchronous Redis client."""
    import redis
    return redis.Redis.from_url(redis_url, decode_responses=True)


def _batch_insert_records(engine, records: list[dict]) -> None:
    """Batch INSERT records into monitoring.request_logs."""
    from sqlalchemy import text

    today = date.today()
    _ensure_partition(engine, today)

    insert_sql = text("""
        INSERT INTO monitoring.request_logs (
            service_name, endpoint, method, status_code, response_time_ms,
            user_id, tenant_id, request_size_bytes, correlation_id,
            error_message, timestamp, date, hour
        ) VALUES (
            :service_name, :endpoint, :method, :status_code, :response_time_ms,
            :user_id, :tenant_id, :request_size_bytes, :correlation_id,
            :error_message, :timestamp, :date, :hour
        )
    """)

    with engine.begin() as conn:
        for record in records:
            try:
                params = {
                    "service_name": record.get("service_name", "unknown"),
                    "endpoint": record.get("endpoint", "/unknown"),
                    "method": record.get("method", "GET"),
                    "status_code": int(record.get("status_code", 0)),
                    "response_time_ms": int(record.get("response_time_ms", 0)),
                    "user_id": record.get("user_id") or None,
                    "tenant_id": record.get("tenant_id") or None,
                    "request_size_bytes": record.get("request_size_bytes"),
                    "correlation_id": record.get("correlation_id"),
                    "error_message": record.get("error_message"),
                    "timestamp": record.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    "date": record.get("date", str(today)),
                    "hour": int(record.get("hour", 0)),
                }
                conn.execute(insert_sql, params)
            except Exception as exc:
                logger.warning("Failed to insert monitoring record: %s", exc)


def _ensure_partition(engine, target_date: date) -> None:
    """Create a date partition if it doesn't exist."""
    from sqlalchemy import text

    partition_name = f"request_logs_{target_date.strftime('%Y_%m_%d')}"
    next_day = target_date + timedelta(days=1)

    create_sql = text(f"""
        CREATE TABLE IF NOT EXISTS monitoring.{partition_name}
        PARTITION OF monitoring.request_logs
        FOR VALUES FROM ('{target_date}') TO ('{next_day}');
    """)

    try:
        with engine.begin() as conn:
            conn.execute(create_sql)
    except Exception as exc:
        # Partition may already exist — that's fine
        logger.debug("Partition check for %s: %s", partition_name, exc)
