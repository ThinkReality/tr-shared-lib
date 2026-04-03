"""
Shared Celery tasks for Layer 2 monitoring persistence.

These tasks use ``@shared_task`` so any service's Celery worker
can pick them up.  They accept ``monitoring_db_url`` and ``redis_url``
as arguments (not from any service's config), making them portable.

Beat schedule (add to each service's ``celery_app.py``)::

    beat_schedule = {
        "monitoring-flush-buffer": {
            "task": "monitoring.flush_buffer",
            "schedule": 60.0,
            "args": [SERVICE_NAME, MONITORING_DB_URL, REDIS_URL],
        },
        "monitoring-aggregate-hourly": {
            "task": "monitoring.aggregate_hourly",
            "schedule": crontab(minute=5),
            "args": [MONITORING_DB_URL],
        },
        "monitoring-aggregate-daily": {
            "task": "monitoring.aggregate_daily",
            "schedule": crontab(hour=1, minute=0),
            "args": [MONITORING_DB_URL],
        },
        "monitoring-create-partition": {
            "task": "monitoring.create_partition",
            "schedule": crontab(hour=23, minute=55),
            "args": [MONITORING_DB_URL],
        },
        "monitoring-cleanup-old-logs": {
            "task": "monitoring.cleanup_old_logs",
            "schedule": crontab(hour=2, minute=0),
            "args": [MONITORING_DB_URL, 90],
        },
    }

All imports below are backward-compatible — existing code that imports
from ``tr_shared.monitoring.tasks`` continues to work unchanged.
"""

from tr_shared.monitoring.tasks._helpers import (
    _batch_insert_records,
    _create_sync_engine,
    _ensure_partition,
    _get_sync_redis,
)
from tr_shared.monitoring.tasks.aggregation import (
    aggregate_daily_metrics,
    aggregate_hourly_metrics,
)
from tr_shared.monitoring.tasks.buffer import flush_monitoring_buffer
from tr_shared.monitoring.tasks.maintenance import (
    cleanup_old_monitoring_logs,
    create_next_day_partition,
)

__all__ = [
    "flush_monitoring_buffer",
    "aggregate_hourly_metrics",
    "aggregate_daily_metrics",
    "create_next_day_partition",
    "cleanup_old_monitoring_logs",
    # helpers re-exported for test access (same as old flat module)
    "_batch_insert_records",
    "_create_sync_engine",
    "_ensure_partition",
    "_get_sync_redis",
]
