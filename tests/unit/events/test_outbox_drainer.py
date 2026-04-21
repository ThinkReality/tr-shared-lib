"""Tests for tr_shared.events.outbox_drainer."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


from tr_shared.events import RetryPolicy, drain_outbox


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        class _Mapping:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return _Mapping(self._rows)


class _FakeSession:
    """Stub AsyncSession: scripted execute() responses + begin() context manager."""

    def __init__(self, rows_for_select: list[dict] | None = None):
        self._rows_for_select = rows_for_select or []
        self.executed: list[tuple[str, dict | None]] = []
        self._select_consumed = False

    async def execute(self, stmt, params=None):
        stmt_str = str(stmt)
        self.executed.append((stmt_str, params))
        if "SELECT" in stmt_str and "undelivered_events" in stmt_str and not self._select_consumed:
            self._select_consumed = True
            return _FakeResult(self._rows_for_select)
        return _FakeResult([])

    def begin(self):
        @asynccontextmanager
        async def _ctx():
            yield
        return _ctx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


def _session_factory(rows: list[dict]):
    """Return a factory whose first call yields a session with ``rows`` to SELECT,
    and subsequent calls yield plain sessions for per-row UPDATEs."""
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeSession(rows_for_select=rows)
        return _FakeSession()

    return _factory, calls


def _sample_row(event_type: str = "admin.x", retry_count: int = 0) -> dict:
    return {
        "id": uuid4(),
        "event_type": event_type,
        "tenant_id": uuid4(),
        "actor_id": None,
        "data": json.dumps({"foo": "bar"}),
        "metadata": json.dumps({"correlation_id": "cid-1"}),
        "retry_count": retry_count,
    }


class TestDrainOutbox:
    async def test_empty_batch(self):
        factory, _ = _session_factory(rows=[])
        producer = MagicMock()
        producer.publish = AsyncMock()
        result = await drain_outbox(
            session_factory=factory,
            producer=producer,
            schema="admin",
        )
        assert result == {"published": 0, "retried": 0, "dead_lettered": 0}
        producer.publish.assert_not_called()

    async def test_publishes_success_marks_published_at(self):
        row = _sample_row()
        factory, _ = _session_factory(rows=[row])
        producer = MagicMock()
        producer.publish = AsyncMock(return_value="eid-1")

        result = await drain_outbox(
            session_factory=factory,
            producer=producer,
            schema="admin",
        )
        assert result["published"] == 1
        assert result["retried"] == 0
        assert result["dead_lettered"] == 0
        producer.publish.assert_awaited_once()
        call_kwargs = producer.publish.call_args.kwargs
        assert call_kwargs["event_type"] == "admin.x"
        assert call_kwargs["correlation_id"] == "cid-1"

    async def test_publish_failure_increments_retry(self):
        row = _sample_row(retry_count=2)
        factory, _ = _session_factory(rows=[row])
        producer = MagicMock()
        producer.publish = AsyncMock(side_effect=RuntimeError("redis down"))

        result = await drain_outbox(
            session_factory=factory,
            producer=producer,
            schema="admin",
            retry_policy=RetryPolicy(max_retries=10),
        )
        assert result == {"published": 0, "retried": 1, "dead_lettered": 0}

    async def test_publish_failure_at_max_retries_dead_letters(self):
        row = _sample_row(retry_count=9)  # next_count = 10 == max_retries
        factory, _ = _session_factory(rows=[row])
        producer = MagicMock()
        producer.publish = AsyncMock(side_effect=RuntimeError("fatal"))

        dlq_cb = AsyncMock()
        result = await drain_outbox(
            session_factory=factory,
            producer=producer,
            schema="admin",
            retry_policy=RetryPolicy(max_retries=10),
            on_dead_letter=dlq_cb,
        )
        assert result == {"published": 0, "retried": 0, "dead_lettered": 1}
        dlq_cb.assert_awaited_once()

    async def test_dlq_callback_failure_does_not_crash_drain(self):
        row = _sample_row(retry_count=9)
        factory, _ = _session_factory(rows=[row])
        producer = MagicMock()
        producer.publish = AsyncMock(side_effect=RuntimeError("fatal"))
        dlq_cb = AsyncMock(side_effect=RuntimeError("slack webhook down"))

        result = await drain_outbox(
            session_factory=factory,
            producer=producer,
            schema="admin",
            retry_policy=RetryPolicy(max_retries=10),
            on_dead_letter=dlq_cb,
        )
        assert result["dead_lettered"] == 1

    async def test_default_retry_policy_max_is_10(self):
        # Not yet at 10 retries => retried, not dead-lettered.
        row = _sample_row(retry_count=8)
        factory, _ = _session_factory(rows=[row])
        producer = MagicMock()
        producer.publish = AsyncMock(side_effect=RuntimeError("x"))

        result = await drain_outbox(
            session_factory=factory,
            producer=producer,
            schema="admin",
        )
        assert result["retried"] == 1
        assert result["dead_lettered"] == 0
