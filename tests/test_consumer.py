"""Tests for tr_shared.events.consumer."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from tr_shared.events.consumer import EventConsumer, InMemoryIdempotencyChecker
from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.retry_policy import RetryPolicy


def _flat_msg(event_type: str = "listing.created", event_id: str = "e1", retries: int = 0):
    meta = {"retries": retries} if retries else {}
    return {
        "event_id": event_id,
        "event_type": event_type,
        "version": "1.0",
        "tenant_id": "t1",
        "timestamp": "2026-01-01",
        "source_service": "svc",
        "actor_id": "a1",
        "data": json.dumps({"entity_id": "x"}),
        "metadata": json.dumps(meta),
    }


class TestParseFlat:
    def test_flat_parsing(self):
        c = EventConsumer(redis_url="redis://localhost", parse_mode="flat")
        env = c._parse("msg-1", _flat_msg())
        assert isinstance(env, EventEnvelope)
        assert env.event_type == "listing.created"

    def test_malformed_returns_none(self):
        c = EventConsumer(redis_url="redis://localhost", parse_mode="flat")
        result = c._parse("msg-1", {"data": "not-json{"})
        assert result is None


class TestParsePayload:
    def test_payload_parsing(self):
        payload = {"event_id": "e1", "event_type": "lead.assigned", "data": {"x": 1}}
        c = EventConsumer(redis_url="redis://localhost", parse_mode="payload")
        env = c._parse("msg-1", {"payload": json.dumps(payload)})
        assert env.event_type == "lead.assigned"

    def test_missing_payload_returns_none(self):
        c = EventConsumer(redis_url="redis://localhost", parse_mode="payload")
        result = c._parse("msg-1", {})
        assert result is None


class TestHandlerResolution:
    def test_exact_match(self):
        c = EventConsumer(redis_url="redis://localhost")
        handler = AsyncMock()
        c.register_handler("listing.created", handler)
        assert c._resolve_handler("listing.created") is handler

    def test_wildcard_match(self):
        c = EventConsumer(redis_url="redis://localhost")
        handler = AsyncMock()
        c.register_handler("lead.*", handler)
        assert c._resolve_handler("lead.assigned") is handler

    def test_no_match_returns_none(self):
        c = EventConsumer(redis_url="redis://localhost")
        assert c._resolve_handler("unknown.type") is None

    def test_decorator_registers(self):
        c = EventConsumer(redis_url="redis://localhost")

        @c.handler("deal.won")
        async def handle_deal(event):
            pass

        assert c._resolve_handler("deal.won") is handle_deal


class TestProcessMessage:
    @pytest.fixture
    def consumer(self):
        c = EventConsumer(
            redis_url="redis://localhost",
            retry_policy=RetryPolicy(max_retries=3),
        )
        c._redis = AsyncMock()
        c._dlq = AsyncMock()
        return c

    async def test_calls_handler_on_match(self, consumer):
        handler = AsyncMock()
        consumer.register_handler("listing.created", handler)
        result = await consumer._process_message("msg-1", _flat_msg())
        assert result is True
        handler.assert_awaited_once()

    async def test_no_handler_returns_true(self, consumer):
        result = await consumer._process_message("msg-1", _flat_msg("unknown.event"))
        assert result is True

    async def test_malformed_goes_to_dlq(self, consumer):
        result = await consumer._process_message("msg-1", {"data": "bad{"})
        assert result is True
        consumer._dlq.move.assert_awaited_once()

    async def test_handler_failure_requeues(self, consumer):
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        consumer.register_handler("listing.created", handler)
        consumer._requeue = AsyncMock()

        result = await consumer._process_message("msg-1", _flat_msg(retries=0))
        assert result is True
        consumer._requeue.assert_awaited_once()

    async def test_max_retries_goes_to_dlq(self, consumer):
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        consumer.register_handler("listing.created", handler)

        msg = _flat_msg(retries=2)  # retry_count=2, max=3, so this is attempt 3 (last)
        result = await consumer._process_message("msg-1", msg)
        assert result is True
        consumer._dlq.move.assert_awaited_once()


class TestIdempotency:
    async def test_skips_duplicate_event(self):
        checker = AsyncMock()
        checker.is_processed = AsyncMock(return_value=True)

        c = EventConsumer(redis_url="redis://localhost", idempotency_checker=checker)
        c._redis = AsyncMock()
        handler = AsyncMock()
        c.register_handler("listing.created", handler)

        result = await c._process_message("msg-1", _flat_msg())
        assert result is True
        handler.assert_not_awaited()

    async def test_marks_processed_on_success(self):
        checker = AsyncMock()
        checker.is_processed = AsyncMock(return_value=False)

        c = EventConsumer(redis_url="redis://localhost", idempotency_checker=checker)
        c._redis = AsyncMock()
        c._dlq = AsyncMock()
        handler = AsyncMock()
        c.register_handler("listing.created", handler)

        await c._process_message("msg-1", _flat_msg())
        checker.mark_processed.assert_awaited_once_with("e1")


class TestInMemoryIdempotencyChecker:
    async def test_not_processed_initially(self):
        checker = InMemoryIdempotencyChecker()
        assert await checker.is_processed("e1") is False

    async def test_mark_then_check(self):
        checker = InMemoryIdempotencyChecker()
        await checker.mark_processed("e1")
        assert await checker.is_processed("e1") is True

    async def test_evicts_oldest_over_limit(self):
        checker = InMemoryIdempotencyChecker()
        for i in range(10_001):
            await checker.mark_processed(f"e{i}")
        # After eviction, oldest half should be gone
        assert len(checker._ids) <= 5002
