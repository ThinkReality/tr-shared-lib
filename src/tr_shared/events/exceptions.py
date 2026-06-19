"""Typed exceptions for the event-publishing pipeline.

Two-tier hierarchy:

* ``EventPublishError`` — base; any failure to publish a domain event.
* ``EventPublishTransportError`` — recoverable transport-layer failure
  (Redis connection lost, timeout, broker overloaded). Best-effort
  callers MAY swallow this; durable callers MAY retry.

Programming errors (``ValueError``, ``TypeError``, ``AttributeError``,
``RuntimeError``) must not be wrapped in these types — they are bugs
and must propagate unhandled.

These live in tr_shared so every service shares one canonical contract
for distinguishing a transient broker failure from a real bug, instead
of each service defining its own.
"""

from __future__ import annotations


class EventPublishError(Exception):
    """Base for all event-publishing failures."""


class EventPublishTransportError(EventPublishError):
    """Transient failure delivering an event to the broker.

    Raised when the broker is unreachable, slow, or rejecting writes
    (Redis ConnectionError, TimeoutError, ResponseError).
    Callers may swallow this in best-effort code paths.
    """
