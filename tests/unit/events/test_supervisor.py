"""RC-3: this scaffolding was copy-pasted into four modules and tested in one.

Deleting the `_install_shutdown_handlers(...)` call left crm-core at 1414 passed and
lead-management at 2 passed. These are the tests that make that mutation red.
"""

import asyncio
import os
import signal
from unittest.mock import MagicMock

import pytest

from tr_shared.events.supervisor import SHUTDOWN_SIGNALS, run_supervised_consumer


class FakeConsumer:
    def __init__(self, *, start_raises: Exception | None = None, block: bool = False) -> None:
        self.started = False
        self.stop_calls = 0
        self._start_raises = start_raises
        self._block = block
        self._release = asyncio.Event()

    async def start(self) -> None:
        self.started = True
        if self._start_raises is not None:
            raise self._start_raises
        if self._block:
            await self._release.wait()

    async def stop(self) -> None:
        self.stop_calls += 1
        self._release.set()


def _logger() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_handlers_are_installed_for_every_shutdown_signal():
    loop = asyncio.get_running_loop()
    consumer = FakeConsumer()
    seen: list[signal.Signals] = []
    real_add = loop.add_signal_handler

    def _spy(sig, cb, *args):
        seen.append(sig)
        return real_add(sig, cb, *args)

    loop.add_signal_handler = _spy  # type: ignore[method-assign]
    try:
        await run_supervised_consumer(lambda: _ready(consumer), logger=_logger())
    finally:
        loop.add_signal_handler = real_add  # type: ignore[method-assign]

    assert seen == list(SHUTDOWN_SIGNALS)


async def _ready(consumer: FakeConsumer) -> FakeConsumer:
    return consumer


@pytest.mark.asyncio
async def test_sigterm_stops_the_consumer():
    """The real thing: a blocked consumer, a real SIGTERM to this process, and the
    consumer must come back down without the wait_for timing out."""
    consumer = FakeConsumer(block=True)

    async def _run() -> None:
        await run_supervised_consumer(lambda: _ready(consumer), logger=_logger())

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.05)
    os.kill(os.getpid(), signal.SIGTERM)

    await asyncio.wait_for(task, timeout=5)

    assert consumer.stop_calls >= 1


@pytest.mark.asyncio
async def test_stop_is_awaited_when_start_raises():
    consumer = FakeConsumer(start_raises=RuntimeError("redis refused"))

    with pytest.raises(RuntimeError):
        await run_supervised_consumer(lambda: _ready(consumer), logger=_logger())

    assert consumer.stop_calls == 1


@pytest.mark.asyncio
async def test_teardown_runs_even_when_start_raises():
    """activity closes its cache provider here; leaking it on a crash-loop leaks a
    Redis connection per restart."""
    consumer = FakeConsumer(start_raises=RuntimeError("boom"))
    torn_down = []

    async def _teardown() -> None:
        torn_down.append(True)

    with pytest.raises(RuntimeError):
        await run_supervised_consumer(
            lambda: _ready(consumer), teardown=_teardown, logger=_logger()
        )

    assert torn_down == [True]


@pytest.mark.asyncio
async def test_setup_runs_before_the_consumer_is_obtained():
    """notification resolves vault secrets in setup; obtaining the consumer first
    would build it against unresolved config."""
    order: list[str] = []
    consumer = FakeConsumer()

    async def _setup() -> None:
        order.append("setup")

    async def _get() -> FakeConsumer:
        order.append("get_consumer")
        return consumer

    await run_supervised_consumer(_get, setup=_setup, teardown=None, logger=_logger())

    assert order == ["setup", "get_consumer"]


@pytest.mark.asyncio
async def test_handlers_are_removed_afterwards():
    """Otherwise a second supervised run in the same process — or a test suite —
    inherits a handler bound to a consumer that is already gone."""
    loop = asyncio.get_running_loop()
    removed: list[signal.Signals] = []
    real_remove = loop.remove_signal_handler

    def _spy(sig):
        removed.append(sig)
        return real_remove(sig)

    loop.remove_signal_handler = _spy  # type: ignore[method-assign]
    try:
        await run_supervised_consumer(lambda: _ready(FakeConsumer()), logger=_logger())
    finally:
        loop.remove_signal_handler = real_remove  # type: ignore[method-assign]

    assert removed == list(SHUTDOWN_SIGNALS)


@pytest.mark.asyncio
async def test_reentry_is_safe_when_a_handler_is_already_installed():
    """add_signal_handler replaces rather than raises, but the second run must still
    leave the loop clean."""
    await run_supervised_consumer(lambda: _ready(FakeConsumer()), logger=_logger())
    consumer = FakeConsumer()
    await run_supervised_consumer(lambda: _ready(consumer), logger=_logger())

    assert consumer.stop_calls == 1
