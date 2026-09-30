import io
import json
import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest
import structlog
from celery.contrib.testing.worker import start_worker
from celery.signals import setup_logging

from tr_shared.celery import log_context
from tr_shared.celery.factory import create_celery_app
from tr_shared.contracts.headers import CELERY_CORRELATION_HEADER
from tr_shared.logging import get_correlation_id

QUEUE = "svc_tasks"
SERVICE = "proplytics-svc"


def _app(**overrides):
    kwargs = {
        "service_name": SERVICE,
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "default_queue": QUEUE,
        "log_level": "INFO",
        "log_format": "json",
        "extra_config": {"broker_transport_options": {"polling_interval": 0.05}},
    }
    kwargs.update(overrides)
    app = create_celery_app(**kwargs)

    @app.task(name="svc.emit", bind=True, shared=False)
    def emit(self, leak=None):
        structlog.get_logger("svc.task").info("task_ran", seen=get_correlation_id())
        if leak:
            structlog.contextvars.bind_contextvars(leak=leak)
        return get_correlation_id()

    @app.task(name="svc.flaky", bind=True, shared=False)
    def flaky(self):
        structlog.get_logger("svc.task").info("task_ran", attempt=self.request.retries)
        if self.request.retries == 0:
            raise self.retry(countdown=0, max_retries=1)
        return get_correlation_id()

    return app


class _Worker:
    def __init__(self, app, sink: io.StringIO) -> None:
        self.app = app
        self._sink = sink

    def run(self, name: str, **kwargs):
        return self.app.tasks[name].apply_async(**kwargs)

    def lines(self, task_id: str) -> list[dict]:
        found = []
        for raw in self._sink.getvalue().splitlines():
            if raw.startswith("{"):
                entry = json.loads(raw)
                if entry.get("event") == "task_ran" and entry.get("task_id") == task_id:
                    found.append(entry)
        return found


@pytest.fixture(scope="module")
def worker():
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers.clear()
    structlog.reset_defaults()
    log_context._logging_config.clear()
    log_context._baseline.clear()
    app = _app()
    try:
        with start_worker(
            app, perform_ping_check=False, pool="solo", loglevel="WARNING", queues=[QUEUE]
        ):
            sink = io.StringIO()
            capture = logging.StreamHandler(sink)
            capture.setFormatter(root.handlers[0].formatter)
            root.addHandler(capture)
            yield _Worker(app, sink)
    finally:
        root.handlers.clear()
        root.handlers.extend(saved_handlers)
        root.setLevel(saved_level)
        structlog.reset_defaults()
        structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _clean_test_thread_context():
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


class TestTheIdFollowsTheTask:
    def test_a_task_published_in_a_bound_context_logs_with_that_id(self, worker):
        structlog.contextvars.bind_contextvars(correlation_id="corr-1")

        result = worker.run("svc.emit")

        assert result.get(timeout=10) == "corr-1"
        (line,) = worker.lines(result.id)
        assert line["correlation_id"] == "corr-1"
        assert line["task_name"] == "svc.emit"
        assert line["task_id"] == result.id

    def test_a_publish_with_no_context_gets_a_fresh_uuid4_each_time(self, worker):
        first = worker.run("svc.emit").get(timeout=10)
        second = worker.run("svc.emit").get(timeout=10)

        assert uuid.UUID(first).version == 4
        assert uuid.UUID(second).version == 4
        assert first != second

    def test_an_explicit_header_is_not_overwritten(self, worker):
        structlog.contextvars.bind_contextvars(correlation_id="ambient")

        result = worker.run("svc.emit", headers={CELERY_CORRELATION_HEADER: "explicit"})

        assert result.get(timeout=10) == "explicit"

    def test_a_retry_keeps_the_id(self, worker):
        structlog.contextvars.bind_contextvars(correlation_id="corr-retry")

        result = worker.run("svc.flaky")

        assert result.get(timeout=20) == "corr-retry"
        assert [line["correlation_id"] for line in worker.lines(result.id)] == ["corr-retry"] * 2


class TestNothingLeaksBetweenTasks:
    def test_a_binding_made_by_one_task_is_gone_in_the_next(self, worker):
        first = worker.run("svc.emit", kwargs={"leak": "from-first"})
        first.get(timeout=10)
        second = worker.run("svc.emit")
        second.get(timeout=10)

        (first_line,) = worker.lines(first.id)
        (second_line,) = worker.lines(second.id)
        assert "leak" not in first_line
        assert "leak" not in second_line
        assert first_line["correlation_id"] != second_line["correlation_id"]


class TestEagerTasksKeepTheCallersContext:
    def test_apply_neither_rebinds_nor_wipes_what_the_caller_bound(self):
        app = _app()
        structlog.contextvars.bind_contextvars(correlation_id="caller", tenant_id="t1")

        result = app.tasks["svc.emit"].apply()

        assert result.get() == "caller"
        assert structlog.contextvars.get_contextvars() == {
            "correlation_id": "caller",
            "tenant_id": "t1",
        }


class TestServiceName:
    def test_task_logs_carry_the_service_name_every_time(self, worker):
        results = [worker.run("svc.emit") for _ in range(2)]
        for result in results:
            result.get(timeout=10)

        assert {worker.lines(r.id)[0]["service_name"] for r in results} == {SERVICE}


class TestSetupLoggingReceiver:
    @pytest.fixture(autouse=True)
    def _isolated_state(self, monkeypatch):
        monkeypatch.setattr(log_context, "_logging_config", {})
        monkeypatch.setattr(log_context, "_baseline", {})

    def _send(self):
        setup_logging.send(sender=None, loglevel=10, logfile=None, format="", colorize=False)

    def test_it_configures_logging_with_the_factorys_settings(self):
        with patch.object(log_context, "configure_logging", MagicMock()) as configure:
            _app(log_level="WARNING", log_format="json", service_name="svc-a")
            self._send()

        configure.assert_called_once_with(
            log_level="WARNING", log_format="json", service_name="svc-a"
        )

    def test_a_second_factory_call_in_one_process_wins(self):
        with patch.object(log_context, "configure_logging", MagicMock()) as configure:
            _app(log_level="INFO", log_format="text", service_name="first")
            _app(log_level="DEBUG", log_format="json", service_name="second")
            self._send()

        configure.assert_called_once_with(
            log_level="DEBUG", log_format="json", service_name="second"
        )

    def test_log_level_and_format_are_required(self):
        with pytest.raises(TypeError):
            create_celery_app(
                service_name="svc",
                broker_url="memory://",
                result_backend="cache+memory://",
                default_queue=QUEUE,
            )
