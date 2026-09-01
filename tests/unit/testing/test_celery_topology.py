"""The guard must fail on a parse it could not make, never return an empty set.

Every spelling below is copied from a real service's start-command file, because
the bug this module replaces was caused by a guard that handled one spelling and
silently reported nothing for the others.
"""

from __future__ import annotations

import pytest

from tr_shared.celery.factory import create_celery_app
from tr_shared.testing.celery_topology import (
    CeleryTopologyError,
    assert_default_queue_is_consumed,
    assert_every_beat_entry_sets_expires,
    assert_every_route_matches_a_task,
    assert_expires_is_not_shorter_than_the_interval,
    assert_no_service_consumes_the_shared_queue,
    assert_topology_is_readable,
    consumed_queues,
    start_command_file,
    unmatched_route_patterns,
)

BROKER = "redis://localhost:6379/1"
BACKEND = "redis://localhost:6379/2"

# tr-api-gateway
Q_SHORT = """#!/bin/bash
case "$ROLE" in
worker) exec celery -A app.celery_app worker -Q gateway_tasks,monitoring --concurrency=4 ;;
esac
"""

# tr-media-service — the flag differs AND the command spans two physical lines.
Q_LONG_CONTINUED = """#!/bin/bash
case "$ROLE" in
worker)
    exec celery -A app.celery_app worker --loglevel=info \\
        --queues=ocr_queue,media_tasks --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
esac
"""

# tr-whatsApp-marketing-agent — the value is defined on an earlier line.
Q_VIA_VARIABLE = """#!/bin/bash
WORKER_QUEUES="wam_default,wam_bulk,campaign_queue"
case "$ROLE" in
worker) exec "${VENV}/celery" -A app.celery_app worker -Q "${WORKER_QUEUES}" ;;
esac
"""


def write(tmp_path, body, name="deploy.sh"):
    (tmp_path / name).write_text(body)
    return tmp_path


def app(**overrides):
    kwargs = {
        "service_name": "svc",
        "broker_url": BROKER,
        "result_backend": BACKEND,
        "default_queue": "gateway_tasks",
    }
    kwargs.update(overrides)
    return create_celery_app(**kwargs)


class TestEverySpellingInLiveUseIsParsed:
    def test_short_flag(self, tmp_path):
        assert consumed_queues(write(tmp_path, Q_SHORT)) == {"gateway_tasks", "monitoring"}

    def test_long_flag_across_a_line_continuation(self, tmp_path):
        """The spelling that made the previous guard read an empty set: `celery …
        worker` and `--queues=` are never on the same physical line."""
        assert consumed_queues(write(tmp_path, Q_LONG_CONTINUED)) == {
            "ocr_queue",
            "media_tasks",
        }

    def test_shell_variable_indirection(self, tmp_path):
        assert consumed_queues(write(tmp_path, Q_VIA_VARIABLE)) == {
            "wam_default",
            "wam_bulk",
            "campaign_queue",
        }

    def test_several_worker_roles_are_unioned(self, tmp_path):
        """tr-content-platform runs two workers on different queue sets, and
        tr-realty-data-hub three. Reading only the first would under-report."""
        body = """#!/bin/bash
case "$ROLE" in
worker-1) exec celery -A app.celery_app worker -Q cms,monitoring ;;
worker-2) exec celery -A app.celery_app worker -Q portal_sync ;;
esac
"""
        assert consumed_queues(write(tmp_path, body)) == {"cms", "monitoring", "portal_sync"}


class TestAnUnreadableParseFailsAndDoesNotReturnEmpty:
    """The core invariant. An empty set satisfies every assertion written over it,
    so returning one is how a guard silently stops guarding."""

    def test_a_worker_line_with_no_queue_flag_raises(self, tmp_path):
        body = "worker) exec celery -A app.celery_app worker --loglevel=info ;;\n"
        with pytest.raises(CeleryTopologyError, match="cannot read a queue list"):
            consumed_queues(write(tmp_path, body))

    def test_an_unresolvable_variable_raises(self, tmp_path):
        """A fourth spelling — two hops of indirection — must go red, not empty."""
        body = 'worker) exec celery -A app.celery_app worker -Q "${NEVER_ASSIGNED}" ;;\n'
        with pytest.raises(CeleryTopologyError, match="cannot read a queue list"):
            consumed_queues(write(tmp_path, body))

    def test_no_start_command_file_at_all_raises(self, tmp_path):
        with pytest.raises(CeleryTopologyError, match="no start-command file"):
            consumed_queues(tmp_path)

    def test_a_file_with_no_worker_line_raises(self, tmp_path):
        """tr-content-platform and tr-lead-management are in this state today: a
        deploy.sh that starts only the API, with the worker command in a dashboard."""
        body = "api) exec uvicorn app.main:app --port 8000 ;;\n"
        with pytest.raises(CeleryTopologyError, match="starts a Celery worker"):
            consumed_queues(write(tmp_path, body))


class TestTheFilenameIsResolvedNotAssumed:
    def test_docker_entrypoint_is_found_when_there_is_no_deploy_sh(self, tmp_path):
        write(tmp_path, Q_SHORT, name="docker-entrypoint.sh")
        assert start_command_file(tmp_path).name == "docker-entrypoint.sh"
        assert consumed_queues(tmp_path) == {"gateway_tasks", "monitoring"}

    def test_the_file_that_starts_the_worker_wins_over_mere_presence(self, tmp_path):
        """Three services keep an api-only deploy.sh beside the entrypoint that
        actually starts the worker. Picking by name would parse the wrong file and
        report nothing."""
        write(tmp_path, "api) exec uvicorn app.main:app ;;\n", name="deploy.sh")
        write(tmp_path, Q_SHORT, name="docker-entrypoint.sh")
        assert start_command_file(tmp_path).name == "docker-entrypoint.sh"


class TestCommentsAreNotParsedAsConfiguration:
    def test_a_queue_named_in_a_comment_is_ignored(self, tmp_path):
        """An earlier guard matched `-Q list` out of its own prose and reported a
        queue named `list`."""
        body = Q_SHORT + "\n# remember to add the queue to the -Q list, e.g. -Q ghost\n"
        assert "ghost" not in consumed_queues(write(tmp_path, body))
        assert "list" not in consumed_queues(write(tmp_path, body))


class TestTheSharedFallbackQueue:
    def test_consuming_celery_fails(self, tmp_path):
        body = "worker) exec celery -A app.celery_app worker -Q gateway_tasks,celery ;;\n"
        with pytest.raises(AssertionError, match="fleet-wide"):
            assert_no_service_consumes_the_shared_queue(app(), write(tmp_path, body))

    def test_defaulting_to_celery_fails_even_when_not_consumed(self, tmp_path):
        """The two directions are separate defects: defaulting to it sends this
        service's tasks away; consuming it eats other services' tasks."""
        celery_app = app()
        celery_app.conf.task_default_queue = "celery"
        with pytest.raises(AssertionError, match="still the shared default"):
            assert_no_service_consumes_the_shared_queue(celery_app, write(tmp_path, Q_SHORT))

    def test_an_owned_default_passes(self, tmp_path):
        assert_no_service_consumes_the_shared_queue(app(), write(tmp_path, Q_SHORT))


class TestTheDefaultQueueMustBeDrained:
    def test_an_undrained_default_fails(self, tmp_path):
        with pytest.raises(AssertionError, match="drained by no worker"):
            assert_default_queue_is_consumed(
                app(default_queue="orphan_tasks"), write(tmp_path, Q_SHORT)
            )

    def test_a_drained_default_passes(self, tmp_path):
        assert_default_queue_is_consumed(app(), write(tmp_path, Q_SHORT))


class TestEveryRouteMustMatchARegisteredTask:
    """The check that would have caught `Media Service.*` the day it shipped."""

    def _with_task(self, name, **overrides):
        celery_app = app(**overrides)

        @celery_app.task(name=name, shared=False)
        def _t():  # pragma: no cover - never executed
            return None

        return celery_app

    def test_a_matching_namespace_route_passes(self):
        celery_app = self._with_task(
            "media.snapshot", default_queue="media_tasks", task_namespace="media"
        )
        assert_every_route_matches_a_task(celery_app)

    def test_a_route_matching_nothing_fails(self):
        celery_app = self._with_task("media.snapshot")
        celery_app.conf.task_routes = {"Media Service.*": {"queue": "Media Service_tasks"}}
        with pytest.raises(AssertionError, match="match no registered task"):
            assert_every_route_matches_a_task(celery_app)

    def test_the_realty_shape_fails_too(self):
        """Hyphens, not whitespace — the instance a whitespace-only validator misses."""
        celery_app = self._with_task("dld.run_etl_task")
        celery_app.conf.task_routes = {
            "tr-realty-data-hub.*": {"queue": "tr-realty-data-hub_tasks"}
        }
        assert unmatched_route_patterns(celery_app) == {"tr-realty-data-hub.*"}

    def test_an_exact_task_name_route_is_matched(self):
        """WAM routes `wam.drain_outbox` by exact name, not glob."""
        celery_app = self._with_task("wam.drain_outbox")
        celery_app.conf.task_routes = {"wam.drain_outbox": {"queue": "wam_bulk"}}
        assert_every_route_matches_a_task(celery_app)

    def test_no_routes_at_all_is_not_a_violation(self):
        assert_every_route_matches_a_task(self._with_task("svc.thing"))


class TestTheGuardsAreNotVacuous:
    """`shared=False` throughout this module is load-bearing, not style. Celery's
    `@app.task` defaults to `shared=True`, which registers the task into *every*
    app in the process — so a task declared in an earlier test appears in a later
    test's supposedly-fresh app, and the empty-registry check below passes for the
    wrong reason depending on test order."""

    def test_an_empty_task_registry_is_reported(self, tmp_path):
        with pytest.raises(AssertionError, match="no tasks registered"):
            assert_topology_is_readable(app(), write(tmp_path, Q_SHORT))

    def test_a_populated_registry_passes(self, tmp_path):
        celery_app = app()

        @celery_app.task(name="svc.thing", shared=False)
        def _t():  # pragma: no cover - never executed
            return None

        assert_topology_is_readable(celery_app, write(tmp_path, Q_SHORT))


class TestBeatEntriesAreBounded:
    def test_a_missing_expires_fails(self):
        celery_app = app(beat_schedule={"job": {"task": "svc.t", "schedule": 60}})
        with pytest.raises(AssertionError, match="without `expires`"):
            assert_every_beat_entry_sets_expires(celery_app)

    def test_expires_present_passes(self):
        celery_app = app(
            beat_schedule={"job": {"task": "svc.t", "schedule": 60, "options": {"expires": 120}}}
        )
        assert_every_beat_entry_sets_expires(celery_app)

    def test_expires_shorter_than_the_interval_fails(self):
        celery_app = app(
            beat_schedule={"job": {"task": "svc.t", "schedule": 300, "options": {"expires": 60}}}
        )
        with pytest.raises(AssertionError, match="discards work"):
            assert_expires_is_not_shorter_than_the_interval(celery_app)

    def test_a_crontab_schedule_is_skipped_not_guessed(self):
        """A crontab has no scalar interval. Comparing `expires` against it would
        raise a TypeError; inventing one would be worse. Its bound is per-entry
        (B1/B2), not mechanical."""
        from celery.schedules import crontab

        celery_app = app(
            beat_schedule={
                "job": {
                    "task": "svc.t",
                    "schedule": crontab(hour=3, minute=0),
                    "options": {"expires": 60},
                }
            }
        )
        assert_expires_is_not_shorter_than_the_interval(celery_app)
