"""Tests for create_celery_app factory."""

import pytest
from celery import Celery

from tr_shared.celery.factory import create_celery_app


class TestCreateCeleryApp:
    def test_returns_celery_instance(self):
        app = create_celery_app(
            service_name="test-svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
        )
        assert isinstance(app, Celery)

    def test_service_name_set(self):
        app = create_celery_app(
            service_name="my-service",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
        )
        assert app.main == "my-service"

    def test_task_serializer_is_json(self):
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
        )
        assert app.conf.task_serializer == "json"

    def test_timezone_is_utc(self):
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
        )
        assert app.conf.timezone == "UTC"

    def test_task_acks_late_true(self):
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
        )
        assert app.conf.task_acks_late is True

    def test_default_task_time_limit(self):
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
        )
        assert app.conf.task_time_limit == 600

    def test_custom_task_time_limit(self):
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
            task_time_limit=300,
        )
        assert app.conf.task_time_limit == 300

    def test_task_modules_included(self):
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
            task_modules=["app.tasks.notifications"],
        )
        assert "app.tasks.notifications" in app.conf.include

    def test_beat_schedule_applied(self):
        schedule = {"daily-job": {"task": "svc.tasks.run", "schedule": 86400}}
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
            beat_schedule=schedule,
        )
        assert app.conf.beat_schedule == schedule

    def test_task_annotations_applied(self):
        annotations = {"app.tasks.expensive": {"time_limit": None}}
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
            task_annotations=annotations,
        )
        assert app.conf.task_annotations == annotations

    def test_extra_config_merged(self):
        app = create_celery_app(
            service_name="svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
            extra_config={"worker_concurrency": 4},
        )
        assert app.conf.worker_concurrency == 4

    def test_queue_routing_includes_service_name(self):
        app = create_celery_app(
            service_name="leads-svc",
            broker_url="redis://localhost:6379/1",
            result_backend="redis://localhost:6379/2",
        )
        routes = app.conf.task_routes
        assert any("leads-svc" in k for k in routes)
