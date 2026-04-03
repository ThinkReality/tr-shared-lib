"""
Buffer flush task — moves monitoring records from Redis to the database.
"""

import logging

from celery import shared_task

from tr_shared.monitoring.tasks._helpers import (
    _batch_insert_records,
    _create_sync_engine,
    _get_sync_redis,
)

logger = logging.getLogger(__name__)


@shared_task(name="monitoring.flush_buffer", ignore_result=True)
def flush_monitoring_buffer(
    service_name: str,
    monitoring_db_url: str,
    redis_url: str,
    batch_size: int = 500,
) -> None:
    """
    Flush Redis buffer for a service into the central monitoring DB.

    Pops up to *batch_size* records per iteration, repeats until
    the buffer is empty.  Auto-creates today's partition if missing.

    Args:
        service_name: Which service's buffer to flush.
        monitoring_db_url: Central monitoring DB connection URL.
        redis_url: Redis connection URL.
        batch_size: Max records to pop per pipeline call.
    """
    from tr_shared.monitoring.redis_buffer import flush_buffer_sync

    redis_client = _get_sync_redis(redis_url)
    engine = _create_sync_engine(monitoring_db_url)

    total_flushed = 0

    try:
        while True:
            records = flush_buffer_sync(redis_client, service_name, batch_size)
            if not records:
                break

            _batch_insert_records(engine, records)
            total_flushed += len(records)

            if len(records) < batch_size:
                break

        if total_flushed > 0:
            logger.info(
                "Flushed %d monitoring records for %s",
                total_flushed, service_name,
            )
    except Exception as exc:
        logger.error("flush_monitoring_buffer failed for %s: %s", service_name, exc)
    finally:
        engine.dispose()
        redis_client.close()
