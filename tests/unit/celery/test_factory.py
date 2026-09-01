"""Tests for create_celery_app factory.

The queue-naming tests here exist because two services shipped a route that
matched nothing. `create_celery_app` used to derive both the route pattern and
the queue from `service_name`, which every service reads from `SERVICE_NAME` —
an env var Railway sets to a human-readable display label. tr-media-service ran
with `task_routes = {'Media Service.*': {'queue': 'Media Service_tasks'}}` and
tr-realty-data-hub with `{'tr-realty-data-hub.*': ...}`. Both matched no task
name and named a queue no worker drained.

Neither was caught, because an inert route breaks nothing on its own: media's
tasks still ran, since each `@task` carries its own `queue=` and the decorator
outranks `task_routes`. The route was dead weight that looked like configuration.
"""

import pytest
from celery import Celery

from tr_shared.celery.factory import create_celery_app

BROKER = "redis://localhost:6379/1"
BACKEND = "redis://localhost:6379/2"


def make(**overrides):
    kwargs = {
        "service_name": "svc",
        "broker_url": BROKER,
        "result_backend": BACKEND,
        "default_queue": "svc_tasks",
    }
    kwargs.update(overrides)
    return create_celery_app(**kwargs)


class TestCreateCeleryApp:
    def test_returns_celery_instance(self):
        assert isinstance(make(service_name="test-svc"), Celery)

    def test_service_name_set(self):
        assert make(service_name="my-service").main == "my-service"

    def test_task_serializer_is_json(self):
        assert make().conf.task_serializer == "json"

    def test_timezone_is_utc(self):
        assert make().conf.timezone == "UTC"

    def test_task_acks_late_true(self):
        assert make().conf.task_acks_late is True

    def test_default_task_time_limit(self):
        assert make().conf.task_time_limit == 600

    def test_custom_task_time_limit(self):
        assert make(task_time_limit=300).conf.task_time_limit == 300

    def test_task_modules_included(self):
        app = make(task_modules=["app.tasks.notifications"])
        assert "app.tasks.notifications" in app.conf.include

    def test_beat_schedule_applied(self):
        schedule = {"daily-job": {"task": "svc.tasks.run", "schedule": 86400}}
        assert make(beat_schedule=schedule).conf.beat_schedule == schedule

    def test_task_annotations_applied(self):
        annotations = {"app.tasks.expensive": {"time_limit": None}}
        assert make(task_annotations=annotations).conf.task_annotations == annotations

    def test_extra_config_merged(self):
        assert make(extra_config={"worker_concurrency": 4}).conf.worker_concurrency == 4


class TestTheDefaultQueueIsOwnedNotInherited:
    """Celery's built-in `task_default_queue` is the literal string `celery`, and
    all nine services share one broker DB. A task falling through to it is drained
    by whichever service happens to subscribe to that name — the gateway did —
    and discarded as unregistered. Silent at both ends."""

    def test_default_queue_is_required(self):
        with pytest.raises(TypeError):
            create_celery_app(service_name="svc", broker_url=BROKER, result_backend=BACKEND)

    def test_default_queue_is_what_the_caller_passed(self):
        assert make(default_queue="media_tasks").conf.task_default_queue == "media_tasks"

    def test_the_shared_celery_queue_is_never_the_default_by_accident(self):
        assert make().conf.task_default_queue != "celery"


class TestQueueNamesAreValidatedAsWireValues:
    # Both are real values the factory produced in production, not invented ones.
    @pytest.mark.parametrize(
        "bad", ["Media Service_tasks", "tr-realty-data-hub_tasks", "", "Q tasks", "_x"]
    )
    def test_an_unroutable_name_cannot_be_constructed(self, bad):
        with pytest.raises(ValueError, match="not a valid Celery name"):
            make(default_queue=bad)

    def test_the_offending_value_is_named_in_the_error(self):
        with pytest.raises(ValueError, match="Media Service_tasks"):
            make(default_queue="Media Service_tasks")

    def test_a_namespace_is_validated_too(self):
        """A route pattern is as unroutable as a queue name, and fails the same
        silent way — it simply matches no task."""
        with pytest.raises(ValueError, match="task_namespace"):
            make(task_namespace="Media Service")

    # Every distinct queue name in live use across the fleet, read from each
    # service's real Celery app on 2026-09-01. The validator must admit all of
    # them; if it rejects one, the charset is wrong, not the service.
    @pytest.mark.parametrize(
        "live",
        [
            "admin_panel_tasks",
            "attendance_sync",
            "campaign_queue",
            "celery",
            "cms",
            "crm_tasks",
            "default",
            "dld_tasks",
            "employee_sync",
            "finance_tasks",
            "followup_queue",
            "gateway_tasks",
            "lead_tasks",
            "lms_generation",
            "lms_service_tasks",
            "maintenance",
            "media_tasks",
            "monitoring",
            "notification_tasks",
            "owner_tasks",
            "pf_scraper",
            "portal_sync",
            "tasks_tasks",
            "wam_bulk",
            "wam_default",
        ],
    )
    def test_every_queue_name_in_live_use_is_accepted(self, live):
        assert make(default_queue=live).conf.task_default_queue == live


class TestRoutingIsExplicitOrAbsent:
    def test_a_namespace_routes_to_the_default_queue(self):
        app = make(default_queue="media_tasks", task_namespace="media")
        assert app.conf.task_routes == {"media.*": {"queue": "media_tasks"}}

    def test_the_route_is_built_from_the_namespace_not_the_service_name(self):
        """The whole defect in one assertion: `service_name` must not reach the
        routing table. It is a display label, not a wire value."""
        app = make(
            service_name="Media Service", default_queue="media_tasks", task_namespace="media"
        )
        assert "Media Service" not in str(app.conf.task_routes)

    def test_no_namespace_means_no_route_at_all(self):
        """tr-realty-data-hub spans three prefixes (`dld`, `owner`, `scraping`),
        so no single namespace is correct for it. Emitting nothing is right;
        emitting a guess is what produced the inert route."""
        assert make().conf.task_routes == {}

    def test_a_caller_may_still_route_explicitly(self):
        app = make(extra_config={"task_routes": {"monitoring.*": {"queue": "monitoring"}}})
        assert app.conf.task_routes == {"monitoring.*": {"queue": "monitoring"}}
