import uuid
from typing import Any

import structlog
from celery.signals import before_task_publish, setup_logging, task_postrun, task_prerun

from tr_shared.contracts.headers import CELERY_CORRELATION_HEADER
from tr_shared.logging import configure_logging, get_correlation_id

_logging_config: dict[str, str] = {}
_baseline: dict[str, Any] = {}


def connect_log_context(*, service_name: str, log_level: str, log_format: str) -> None:
    _logging_config.update(service_name=service_name, log_level=log_level, log_format=log_format)
    before_task_publish.connect(
        _stamp_correlation_id, weak=False, dispatch_uid="tr_shared.log_context.stamp"
    )
    task_prerun.connect(_bind_task_context, weak=False, dispatch_uid="tr_shared.log_context.bind")
    task_postrun.connect(
        _restore_baseline, weak=False, dispatch_uid="tr_shared.log_context.restore"
    )
    setup_logging.connect(
        _configure_worker_logging, weak=False, dispatch_uid="tr_shared.log_context.setup"
    )


def _stamp_correlation_id(headers: dict[str, Any] | None = None, **_kwargs: Any) -> None:
    if headers is not None:
        headers.setdefault(CELERY_CORRELATION_HEADER, get_correlation_id() or str(uuid.uuid4()))


def _bind_task_context(task: Any = None, task_id: str | None = None, **_kwargs: Any) -> None:
    if task.request.is_eager:
        return
    _rebind(
        correlation_id=getattr(task.request, CELERY_CORRELATION_HEADER, None) or str(uuid.uuid4()),
        task_id=task_id,
        task_name=task.name,
    )


def _restore_baseline(task: Any = None, **_kwargs: Any) -> None:
    if task.request.is_eager:
        return
    _rebind()


def _rebind(**fields: Any) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**_baseline, **fields)


def _configure_worker_logging(**_kwargs: Any) -> None:
    configure_logging(**_logging_config)
    _baseline.clear()
    _baseline.update(structlog.contextvars.get_contextvars())
