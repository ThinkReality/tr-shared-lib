"""
Shared Celery tasks for Layer 2 monitoring persistence.

These tasks use ``@shared_task`` so any service's Celery worker
can pick them up.  They accept ``monitoring_db_url`` and ``redis_url``
as arguments (not from any service's config), making them portable.

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
