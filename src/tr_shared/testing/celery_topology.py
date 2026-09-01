"""A queue nobody drains, and a route that matches nothing.

Both are silent. Celery does not care whether a queue has a consumer: `send_task`
succeeds, the message lands in Redis, and it sits there — no exception, no log, no
metric. Every suite stays green, because unit tests patch `.delay`, integration
tests run eager, and neither asks a broker anything.

Three production defects motivate the checks here, all found on 2026-09-01:

* **The shared fallback.** `task_default_queue` left unset is the literal string
  ``celery``. All nine services share one broker DB, and the gateway's worker
  subscribed to ``celery``. A task in any of five services matching no route and
  declaring no ``queue=`` was therefore consumed by the *gateway*, which raised
  ``KeyError`` on an unregistered name and discarded it. Silent at both ends.
* **The inert route.** The factory used to derive routing from ``SERVICE_NAME``,
  which Railway sets to a display label. tr-media-service ran with
  ``{'Media Service.*': {'queue': 'Media Service_tasks'}}`` and tr-realty-data-hub
  with ``{'tr-realty-data-hub.*': ...}``. Neither matched any task name.
* **The vacuous guard.** Two services already had a version of this check, copied
  rather than shared, and they had diverged. One parsed only ``-Q`` and so read an
  empty queue set on the service using ``--queues=`` — then asserted successfully
  over nothing.

That last one is why this module refuses to return an empty set. **A parse that
could not be made is an error, never an empty answer.** Six services spell their
queue list three different ways across two filenames; a seventh spelling must go
red on the day it appears rather than quietly switching the guard off.

The shell script is parsed as text on purpose: it is the artifact the deploy
platform executes. A Python constant agreeing with a shell string it cannot see is
not a guarantee.

Usage, per service, under ``tests/architecture/``::

    from pathlib import Path
    from app.celery_app import celery_app
    from tr_shared.testing.celery_topology import (
        assert_default_queue_is_consumed,
        assert_every_route_matches_a_task,
        assert_no_service_consumes_the_shared_queue,
    )

    ROOT = Path(__file__).resolve().parents[2]

    def test_default_queue_is_drained():
        assert_default_queue_is_consumed(celery_app, ROOT)
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # `celery` is an optional extra and this module is imported eagerly by
    # tr_shared.testing.__init__. Importing it at runtime would make the testing
    # extra unusable without the celery extra. `from __future__ import
    # annotations` above keeps these hints lazy.
    from celery import Celery

# The queue list lives in whichever of these the service uses. Order is fixed so
# the answer does not depend on directory listing order.
START_COMMAND_FILES = ("deploy.sh", "docker-entrypoint.sh")

# Celery's built-in default. Shared by every service on one broker DB, which is
# what makes it dangerous rather than merely untidy.
SHARED_DEFAULT_QUEUE = "celery"

_WORKER = re.compile(r"\bcelery\b[^\n]*?\bworker\b")
_Q_SHORT = re.compile(r"-Q[=\s]+(\S+)")
_Q_LONG = re.compile(r"--queues[=\s]+(\S+)")
_SHELL_VAR = re.compile(r"^\$\{?(\w+)\}?$")


class CeleryTopologyError(AssertionError):
    """Raised when the topology cannot be determined — never when it is merely empty.

    Subclasses AssertionError so a service's test fails rather than errors.
    """


def _logical_lines(text: str) -> list[str]:
    """Comment-stripped lines with backslash continuations joined.

    Both steps are load-bearing. tr-media-service splits its worker command across
    two physical lines, so ``celery … worker`` and ``--queues=…`` never appear on
    the same one. And an earlier draft of a guard like this matched the string
    ``-Q list`` out of its own explanatory comment and reported a queue named
    ``list``.
    """
    stripped = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return [ln for ln in stripped.replace("\\\n", " ").splitlines() if ln.strip()]


def _resolve_variable(name: str, text: str) -> str | None:
    """One level of shell indirection: ``-Q "${WORKER_QUEUES}"``.

    Deliberately not recursive. A queue list defined through two hops is a spelling
    nobody uses today, and guessing at it would be the tolerant-parser mistake this
    module exists to avoid — it returns None, and the caller raises.
    """
    match = re.search(rf'^\s*{re.escape(name)}=["\']?([^"\'\n]+)["\']?', text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _queues_from_value(value: str, text: str) -> set[str]:
    value = value.strip().strip("\"'")
    if var := _SHELL_VAR.match(value):
        resolved = _resolve_variable(var.group(1), text)
        if resolved is None:
            return set()
        value = resolved.strip().strip("\"'")
    return {q.strip() for q in value.split(",") if q.strip() and "$" not in q}


def start_command_file(service_root: Path) -> Path:
    """The first start-command file that actually launches a Celery worker.

    Resolving by name alone is what made a copied guard pass vacuously: three
    services keep their list in ``docker-entrypoint.sh``, and a guard hardcoding
    ``deploy.sh`` parsed a file with no queues in it and asserted over the empty
    set it got back.
    """
    present = [service_root / name for name in START_COMMAND_FILES]
    existing = [p for p in present if p.exists()]
    if not existing:
        raise CeleryTopologyError(
            f"no start-command file in {service_root}. Looked for "
            f"{', '.join(START_COMMAND_FILES)}. The worker's queue list is then "
            f"only in the deploy platform's dashboard, where nothing can check it."
        )
    for path in existing:
        if _WORKER.search("\n".join(_logical_lines(path.read_text()))):
            return path
    raise CeleryTopologyError(
        f"none of {[p.name for p in existing]} in {service_root} starts a Celery "
        f"worker. If this service has a worker, its start command lives only in the "
        f"dashboard; commit it so this guard can read it."
    )


def consumed_queues(service_root: Path) -> set[str]:
    """Every queue this service's worker roles subscribe to.

    Raises rather than returning an empty set when a worker line is present but
    unparseable — the whole point of the module.
    """
    path = start_command_file(service_root)
    text = path.read_text()
    lines = _logical_lines(text)

    queues: set[str] = set()
    unparsed: list[str] = []
    for line in lines:
        if not _WORKER.search(line):
            continue
        found: set[str] = set()
        for pattern in (_Q_SHORT, _Q_LONG):
            for raw in pattern.findall(line):
                found |= _queues_from_value(raw, text)
        if found:
            queues |= found
        else:
            unparsed.append(line.strip())

    if unparsed:
        raise CeleryTopologyError(
            f"{path.name} starts a Celery worker on a line this guard cannot read a "
            f"queue list from:\n  "
            + "\n  ".join(unparsed)
            + '\n\nKnown spellings: `-Q a,b`, `--queues=a,b`, and `-Q "${VAR}"` with '
            "VAR assigned earlier in the same file. Failing rather than returning an "
            "empty set is deliberate: an empty set satisfies every assertion written "
            "over it, which is how a copied version of this guard silently stopped "
            "checking anything."
        )
    if not queues:
        raise CeleryTopologyError(
            f"{path.name} names no queues for any worker role — nothing to check."
        )
    return queues


def registered_task_names(app: Celery) -> set[str]:
    """What the worker holds after boot, not what the test happened to import."""
    for module in app.conf.include or []:
        __import__(module)
    return {str(name) for name in app.tasks if not str(name).startswith("celery.")}


def route_patterns(app: Celery) -> set[str]:
    routes = app.conf.task_routes or {}
    return {str(k) for k in routes} if isinstance(routes, dict) else set()


def unmatched_route_patterns(app: Celery) -> set[str]:
    """Route patterns matching no registered task.

    Celery matches these with fnmatch, so an exact task name and a `prefix.*` glob
    are both handled here the same way Celery handles them.
    """
    names = registered_task_names(app)
    return {
        pattern
        for pattern in route_patterns(app)
        if not any(fnmatch.fnmatchcase(name, pattern) for name in names)
    }


def assert_topology_is_readable(app: Celery, service_root: Path) -> None:
    """Guards the guards. Every assertion below is vacuous over an empty input, and
    both inputs can silently become empty — a renamed script, an unpopulated task
    registry.
    """
    assert consumed_queues(service_root), "no consumed queues parsed"
    assert registered_task_names(app), (
        "no tasks registered — every routing assertion would pass over nothing. "
        "Check that `conf.include` names this service's task modules."
    )


def assert_default_queue_is_consumed(app: Celery, service_root: Path) -> None:
    default = str(app.conf.task_default_queue)
    consumed = consumed_queues(service_root)
    assert default in consumed, (
        f"task_default_queue={default!r} is drained by no worker "
        f"(this service consumes {sorted(consumed)}). Every task that matches no "
        f"route and declares no queue= is accepted by the broker and never runs."
    )


def assert_no_service_consumes_the_shared_queue(app: Celery, service_root: Path) -> None:
    """Nobody subscribes to `celery`, and nobody defaults to it.

    Both directions matter. Defaulting to it means this service's unrouted tasks go
    somewhere shared; subscribing to it means this service eats *other* services'
    unrouted tasks and discards them as unregistered.
    """
    consumed = consumed_queues(service_root)
    assert SHARED_DEFAULT_QUEUE not in consumed, (
        f"this service's worker drains {SHARED_DEFAULT_QUEUE!r}, the fleet-wide "
        f"Celery default. Every service shares one broker DB, so it will receive "
        f"other services' unrouted tasks and discard them as unregistered."
    )
    assert str(app.conf.task_default_queue) != SHARED_DEFAULT_QUEUE, (
        f"task_default_queue is still the shared default {SHARED_DEFAULT_QUEUE!r}. "
        f"Pass an explicit default_queue owned by this service."
    )


def assert_every_route_matches_a_task(app: Celery) -> None:
    """The check that would have caught `Media Service.*` on the day it shipped.

    A route matching nothing is not inert in the harmless sense: it looks like
    configuration, so the next reader assumes routing is handled.
    """
    unmatched = unmatched_route_patterns(app)
    assert not unmatched, (
        f"these task_routes patterns match no registered task: {sorted(unmatched)}. "
        f"Registered names are {sorted(registered_task_names(app))[:8]}… — the "
        f"pattern is dead config. Never derive a route from SERVICE_NAME."
    )


def assert_every_beat_entry_targets_a_consumed_queue(app: Celery, service_root: Path) -> None:
    """A beat entry names its queue in `options`, which outranks both the route and
    the decorator — so it can miss in a way the route check cannot see."""
    consumed = consumed_queues(service_root)
    orphans = sorted(
        f"{name} -> {queue}"
        for name, entry in (app.conf.beat_schedule or {}).items()
        if (queue := (entry.get("options") or {}).get("queue")) and queue not in consumed
    )
    assert not orphans, f"beat sends work to queues no worker drains: {orphans}"


def assert_every_beat_entry_sets_expires(app: Celery) -> None:
    """Beat is at-least-once and a consumer outage is unbounded without this.

    `expires` does not drain a queue — Redis lists have no per-element TTL and only
    a running worker evaluates the header. What it bounds is *recovery*: on
    2026-08-29 the gateway's worker lost its broker connection and beat published
    2/min into a queue nobody read for 2.6 days, reaching 7,561 messages. Restarting
    then meant grinding through every stale copy.
    """
    unbounded = sorted(
        name
        for name, entry in (app.conf.beat_schedule or {}).items()
        if (entry.get("options") or {}).get("expires") is None
    )
    assert not unbounded, (
        f"beat entries publish without `expires`: {unbounded}. A queued copy stays "
        f"valid forever, so a consumer outage becomes an unbounded backlog and "
        f"recovery has to process every stale copy."
    )


def assert_expires_is_not_shorter_than_the_interval(app: Celery) -> None:
    """Below the publish interval, a copy that was never stale is discarded while
    merely waiting its turn behind a healthy run."""
    for name, entry in (app.conf.beat_schedule or {}).items():
        options = entry.get("options") or {}
        expires, schedule = options.get("expires"), entry.get("schedule")
        if expires is None or not isinstance(schedule, (int, float)):
            continue  # crontab intervals are not a scalar; expiry bound is per-entry
        assert expires >= schedule, (
            f"{name}: expires={expires}s < schedule={schedule}s — discards work that "
            f"is still fresh."
        )
