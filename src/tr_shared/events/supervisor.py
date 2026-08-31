"""Run an event consumer as a supervised process.

The scaffolding below existed character-for-character in four modules across two
repos — tr-crm-core's activity, notification and learning consumers, and
tr-lead-management's lead consumer — differing only in which logger they called and
whether the consumer was passed or read from a module global. Exactly one of the four
had a test pinning the *call*, so deleting ``_install_shutdown_handlers(...)`` from the
other three left **1414 passed** in crm-core and **2 passed** in lead-management.

One implementation, tested once, is the fix. Copying the one test into three more
places would have left four copies to keep in sync.

Why it matters that SIGTERM is handled at all: ``docker stop`` sends SIGTERM, and
without a handler the process is killed mid-batch, so stream offsets never commit and
the next start re-delivers whatever was in flight.
"""

from __future__ import annotations

import asyncio
import functools
import signal
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from tr_shared.logging import get_logger

_default_logger = get_logger(__name__)

# SIGINT is here for an interactive `docker compose up`; SIGTERM is what actually
# stops the process in every deployed environment.
SHUTDOWN_SIGNALS = (signal.SIGTERM, signal.SIGINT)


class SupervisableConsumer(Protocol):
    """The two methods this helper drives. A Protocol rather than ``EventConsumer``
    so a test can supervise a stub without building a Redis client."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


def _install_shutdown_handlers(
    consumer: SupervisableConsumer,
    shutdown_tasks: set[asyncio.Task[None]],
    logger: Any,
) -> list[signal.Signals]:
    loop = asyncio.get_running_loop()

    async def _stop(sig: signal.Signals) -> None:
        logger.info("Shutdown signal received", extra={"signal": sig.name})
        await consumer.stop()

    def _on_signal(sig: signal.Signals) -> None:
        # The set keeps a strong reference. Without it the only reference to this
        # task is the event loop's weak one, so it can be collected mid-shutdown and
        # the consumer never actually stops.
        task = asyncio.create_task(_stop(sig))
        shutdown_tasks.add(task)
        task.add_done_callback(shutdown_tasks.discard)

    installed: list[signal.Signals] = []
    for sig in SHUTDOWN_SIGNALS:
        try:
            # add_signal_handler replaces any existing handler for the signal rather
            # than raising, so re-entry is safe; the finally below puts the loop back
            # the way it was found.
            loop.add_signal_handler(sig, functools.partial(_on_signal, sig))
        except (NotImplementedError, RuntimeError):
            # No signal handling off the main thread, or on platforms without it.
            # A consumer that cannot register is still a consumer worth running.
            logger.warning("Could not install handler for %s", sig.name)
            continue
        installed.append(sig)
    return installed


def _remove_shutdown_handlers(installed: list[signal.Signals]) -> None:
    loop = asyncio.get_running_loop()
    for sig in installed:
        loop.remove_signal_handler(sig)


async def run_supervised_consumer(
    get_consumer: Callable[[], Awaitable[SupervisableConsumer]],
    *,
    setup: Callable[[], Awaitable[None]] | None = None,
    teardown: Callable[[], Awaitable[None]] | None = None,
    logger: Any | None = None,
) -> None:
    """Install shutdown handlers, run the consumer, and always stop it.

    ``setup`` runs before the consumer is obtained — notification resolves vault
    secrets there. ``teardown`` runs after the consumer has stopped, including when
    ``start()`` raised — activity closes its cache provider there.

    Deliberately two hooks and no more. If a caller does not fit, the caller is the
    thing to fix: a third hook would mean this helper is being shaped by one awkward
    call site rather than by what the four of them share.
    """
    log = logger if logger is not None else _default_logger
    shutdown_tasks: set[asyncio.Task[None]] = set()

    if setup is not None:
        await setup()

    consumer = await get_consumer()
    installed = _install_shutdown_handlers(consumer, shutdown_tasks, log)

    try:
        await consumer.start()
    finally:
        # stop() is idempotent, so running it here as well as from the signal path
        # covers the case where start() returned or raised on its own.
        await consumer.stop()
        _remove_shutdown_handlers(installed)
        if teardown is not None:
            await teardown()
