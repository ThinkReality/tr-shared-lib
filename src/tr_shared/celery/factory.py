"""
Shared Celery app factory — eliminates the 45-111 lines of duplicated
Celery configuration found in every service's celery_app.py.

Usage in any service (~10 lines instead of 45-111)::

    from celery.schedules import crontab
    from tr_shared.celery import create_celery_app
    from app.core.config import get_settings

    settings = get_settings()
    celery_app = create_celery_app(
        service_name=settings.SERVICE_NAME,
        broker_url=settings.CELERY_BROKER_URL,
        result_backend=settings.CELERY_RESULT_BACKEND,
        task_modules=["app.tasks"],
        beat_schedule={
            "daily-cleanup": {
                "task": "app.tasks.cleanup.run",
                "schedule": crontab(hour=2, minute=0),
            },
        },
    )
"""

from celery import Celery


def create_celery_app(
    service_name: str,
    broker_url: str,
    result_backend: str,
    task_modules: list[str] | None = None,
    beat_schedule: dict | None = None,
    task_time_limit: int = 600,
    task_soft_time_limit: int = 540,
    worker_prefetch_multiplier: int = 1,
    task_annotations: dict | None = None,
    dead_letter_queue: str | None = None,
    extra_config: dict | None = None,
) -> Celery:
    """
    Create a pre-configured Celery application.

    Args:
        service_name: Unique service identifier (used for queue routing).
        broker_url: Redis URL for the Celery broker (DB 1).
        result_backend: Redis URL for task results (DB 2).
        task_modules: List of module paths for auto-discovery.
        beat_schedule: Periodic task schedule dict.
        task_time_limit: Hard time limit per task in seconds.
        task_soft_time_limit: Soft time limit (SoftTimeLimitExceeded raised).
        worker_prefetch_multiplier: How many tasks a worker prefetches.
        task_annotations: Per-task overrides (e.g., disable time limits).
        dead_letter_queue: Optional queue name for tasks that exhaust retries.
        extra_config: Additional Celery config to merge in.
    """
    app = Celery(service_name, broker=broker_url, backend=result_backend)

    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        task_time_limit=task_time_limit,
        task_soft_time_limit=task_soft_time_limit,
        worker_prefetch_multiplier=worker_prefetch_multiplier,
        worker_disable_rate_limits=False,
        result_expires=3600,
        task_routes={
            f"{service_name}.*": {"queue": f"{service_name}_tasks"},
        },
    )

    if task_modules:
        app.conf.include = task_modules

    if beat_schedule:
        app.conf.beat_schedule = beat_schedule

    if task_annotations:
        app.conf.task_annotations = task_annotations

    if dead_letter_queue:
        app.conf.task_default_dead_letter_queue = dead_letter_queue

    if extra_config:
        app.conf.update(extra_config)

    return app
