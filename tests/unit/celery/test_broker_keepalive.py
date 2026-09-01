"""The broker connection must be able to notice its peer went away.

kombu already enables redis-py's `health_check_interval`, which is why this was
not obviously missing: it looks like connection health is handled. It is not, for
the one state that matters. redis-py checks health *before issuing a command* on
a pooled connection; a worker sits blocked inside BRPOP, where no command is
pending, so the check never runs. The peer disappears, the read never returns,
and because nothing raises, `broker_connection_retry` never fires either.

tr-api-gateway lost its broker connection this way on 2026-08-29 02:52 UTC and
stayed silently dead for 2.6 days — `inspect()` answered the whole time, because
the control channel is a separate socket that reconnects normally. Every probe
called the worker healthy while its queue grew to 7,561.

TCP keepalive is the only mechanism that acts on a blocked socket, and it is off
by default.
"""

from __future__ import annotations

import socket

import pytest

from tr_shared.celery.factory import (
    BROKER_TRANSPORT_OPTIONS,
    TCP_KEEPALIVE_OPTIONS,
    create_celery_app,
)

BROKER = "redis://localhost:6379/1"
BACKEND = "redis://localhost:6379/2"


@pytest.fixture
def app():
    return create_celery_app("svc", BROKER, BACKEND, "svc_tasks")


class TestTheBrokerSocketIsKeptAlive:
    def test_keepalive_is_enabled(self, app) -> None:
        assert app.conf.broker_transport_options["socket_keepalive"] is True

    def test_keepalive_is_actually_tuned(self, app) -> None:
        """`socket_keepalive` alone is nearly inert: Linux defaults TCP_KEEPIDLE
        to 7200s, so a dead peer would go unnoticed for two hours."""
        assert app.conf.broker_transport_options["socket_keepalive_options"]

    def test_the_options_are_real_socket_constants(self, app) -> None:
        """Keys must be the platform's own constants — redis-py passes them
        straight to setsockopt, where a wrong key is an error, not a no-op."""
        known = {
            getattr(socket, name)
            for name in ("TCP_KEEPIDLE", "TCP_KEEPINTVL", "TCP_KEEPCNT", "TCP_KEEPALIVE")
            if hasattr(socket, name)
        }
        assert set(TCP_KEEPALIVE_OPTIONS) <= known

    def test_absent_constants_are_skipped_not_guessed(self) -> None:
        """macOS has no TCP_KEEPIDLE, Linux does. Hardcoding the numbers would
        make this import-time crash on one platform or set a wrong option on the
        other, so each name is looked up and a missing one is dropped."""
        assert all(isinstance(option, int) for option in TCP_KEEPALIVE_OPTIONS)
        if hasattr(socket, "TCP_KEEPINTVL"):
            assert socket.TCP_KEEPINTVL in TCP_KEEPALIVE_OPTIONS

    def test_kombu_accepts_every_option_name_we_set(self) -> None:
        """Pins the names against the installed transport rather than against
        docs. kombu silently ignores an option it does not know, so a typo here
        would leave keepalive off with every assertion above still green."""
        from kombu.transport.redis import Transport

        supported = set(Transport.Channel.connection_class_ssl.__init__.__code__.co_varnames)
        supported |= set(Transport.Channel.from_transport_options)
        assert set(BROKER_TRANSPORT_OPTIONS) <= supported, set(BROKER_TRANSPORT_OPTIONS) - supported


class TestTheResultBackendToo:
    """A second connection, with its own settings and its own corpse in the same
    incident. `broker_transport_options` does not reach it."""

    def test_result_backend_keepalive_is_enabled(self, app) -> None:
        assert app.conf.redis_socket_keepalive is True

    def test_result_backend_health_check_is_set(self, app) -> None:
        assert app.conf.redis_backend_health_check_interval

    def test_celery_reads_the_names_we_set(self) -> None:
        """Same pinning as above, on the backend's own option names."""
        from pathlib import Path

        import celery.backends.redis as backend

        source = Path(backend.__file__).read_text()
        for name in (
            "redis_socket_keepalive",
            "redis_retry_on_timeout",
            "redis_backend_health_check_interval",
        ):
            assert f"'{name}'" in source, name


class TestRuntimeReconnectionIsOn:
    def test_retry_covers_more_than_startup(self, app) -> None:
        """Pins the effective values, not our setting of them: only
        `..._on_startup` needs setting (Celery defaults it to None), while
        runtime retry is already True by default — an explicit line for it was
        removed once a mutation showed removing it changed nothing.

        Neither flag would have helped the gateway: retry fires on a raised
        error, and a half-open socket raises nothing. They matter for every
        *other* broker failure, which is why they are still pinned.
        """
        assert app.conf.broker_connection_retry_on_startup is True
        assert app.conf.broker_connection_retry is True


class TestCallerOptionsMergeRatherThanReplace:
    def test_a_caller_option_does_not_drop_keepalive(self) -> None:
        """`conf.update` swaps the whole dict. Without merging, a service adding
        one unrelated option would silently reopen the exact failure above."""
        app = create_celery_app(
            "svc",
            BROKER,
            BACKEND,
            "svc_tasks",
            extra_config={"broker_transport_options": {"visibility_timeout": 3600}},
        )
        options = app.conf.broker_transport_options
        assert options["visibility_timeout"] == 3600
        assert options["socket_keepalive"] is True
        assert options["socket_keepalive_options"]

    def test_a_caller_may_still_override_deliberately(self) -> None:
        app = create_celery_app(
            "svc",
            BROKER,
            BACKEND,
            "svc_tasks",
            extra_config={"broker_transport_options": {"socket_keepalive": False}},
        )
        assert app.conf.broker_transport_options["socket_keepalive"] is False

    def test_unrelated_extra_config_is_untouched(self) -> None:
        app = create_celery_app(
            "svc",
            BROKER,
            BACKEND,
            "svc_tasks",
            extra_config={
                "beat_schedule_filename": "/tmp/x",
                "task_routes": {"a.*": {"queue": "q"}},
            },
        )
        assert app.conf.beat_schedule_filename == "/tmp/x"
        assert app.conf.task_routes == {"a.*": {"queue": "q"}}
        assert app.conf.broker_transport_options["socket_keepalive"] is True

    def test_the_module_default_is_not_mutated_by_a_caller(self) -> None:
        """The factory hands out a copy. A shared dict would let one service's
        override leak into every app built afterwards in the same process."""
        create_celery_app(
            "svc",
            BROKER,
            BACKEND,
            "svc_tasks",
            extra_config={"broker_transport_options": {"socket_keepalive": False}},
        )
        assert BROKER_TRANSPORT_OPTIONS["socket_keepalive"] is True
        assert (
            create_celery_app(
                "other", BROKER, BACKEND, "other_tasks"
            ).conf.broker_transport_options["socket_keepalive"]
            is True
        )
