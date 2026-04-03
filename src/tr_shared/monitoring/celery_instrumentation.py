"""
Celery task instrumentation via OTel signal handlers.

Hooks into Celery's ``task_prerun``, ``task_failure``, and ``task_postrun``
signals to record three metrics:

- ``celery_task_duration_seconds`` — histogram of task execution time.
- ``celery_tasks`` — counter of completions, by task name and success/failure.
- ``celery_tasks_active`` — up-down counter of in-flight tasks.

**Must be called AFTER** ``setup_monitoring()`` so the global ``MeterProvider``
is configured.  Safe to call multiple times — only the first call has effect.

Usage::

    from tr_shared.monitoring import setup_celery_instrumentation

    # in main.py (or Celery worker startup), after setup_monitoring(...)
    setup_celery_instrumentation()
"""

import logging
import threading
import time

from cachetools import TTLCache
from celery.signals import task_failure, task_postrun, task_prerun
from opentelemetry import metrics

logger = logging.getLogger(__name__)

# Guard: prevent double-registration across multiple imports or calls.
_instrumented: bool = False
_instrumented_lock: threading.Lock = threading.Lock()


def setup_celery_instrumentation() -> None:
    """Register OTel Celery metrics via Celery signal handlers.

    Idempotent — calling this more than once is safe; subsequent calls are
    silently ignored.
    """
    global _instrumented
    with _instrumented_lock:
        if _instrumented:
            logger.debug("Celery OTel instrumentation already registered; skipping")
            return
        _instrumented = True

    meter = metrics.get_meter("tr_shared.monitoring.celery")

    celery_task_duration = meter.create_histogram(
        "celery_task_duration_seconds",
        description="Celery task execution duration",
        unit="s",
    )
    celery_task_total = meter.create_counter(
        "celery_tasks",
        description="Total Celery task executions",
        unit="{task}",
    )
    celery_task_active = meter.create_up_down_counter(
        "celery_tasks_active",
        description="Currently active Celery tasks",
        unit="{task}",
    )

    # TTLCache prevents unbounded memory growth if postrun is never called.
    task_start_times: TTLCache = TTLCache(maxsize=10_000, ttl=3600)
    task_start_times_lock = threading.Lock()
    failed_task_ids: TTLCache = TTLCache(maxsize=10_000, ttl=3600)
    failed_task_ids_lock = threading.Lock()

    @task_prerun.connect
    def _task_prerun(sender=None, task_id=None, task=None, **kwargs):
        with task_start_times_lock:
            task_start_times[task_id] = time.perf_counter()
        celery_task_active.add(1, {"task.name": task.name})

    @task_failure.connect
    def _task_failure(sender=None, task_id=None, task=None, **kwargs):
        with failed_task_ids_lock:
            failed_task_ids[task_id] = True

    @task_postrun.connect
    def _task_postrun(sender=None, task_id=None, task=None, **kwargs):
        is_failed = False
        with failed_task_ids_lock:
            is_failed = failed_task_ids.pop(task_id, False)

        start_time = None
        with task_start_times_lock:
            start_time = task_start_times.pop(task_id, None)

        if start_time is None:
            logger.warning(
                "Task start time not found (TTLCache eviction?). "
                "task_id=%s task_name=%s active_tasks=%d",
                task_id,
                getattr(task, "name", "unknown"),
                len(task_start_times),
            )

        task_name = getattr(task, "name", "unknown")
        status = "failure" if is_failed else "success"
        labels = {"task.name": task_name, "status": status}

        celery_task_total.add(1, labels)

        if start_time is not None:
            celery_task_duration.record(time.perf_counter() - start_time, labels)

        celery_task_active.add(-1, {"task.name": task_name})

    logger.info("Celery task OTel instrumentation registered")
