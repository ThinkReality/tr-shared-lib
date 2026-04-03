"""Tests for InMemoryIdempotencyChecker and EventConsumer silent-drop fixes."""

import json
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tr_shared.events.consumer import EventConsumer, InMemoryIdempotencyChecker


# ---------------------------------------------------------------------------
# InMemoryIdempotencyChecker — Fix 4 (OrderedDict FIFO eviction)
# ---------------------------------------------------------------------------


class TestInMemoryIdempotencyChecker:
    async def test_mark_and_check_basic(self):
        checker = InMemoryIdempotencyChecker()
        await checker.mark_processed("evt-1")
        assert await checker.is_processed("evt-1") is True

    async def test_unknown_id_returns_false(self):
        checker = InMemoryIdempotencyChecker()
        assert await checker.is_processed("evt-unknown") is False

    def test_internal_storage_is_ordered_dict(self):
        checker = InMemoryIdempotencyChecker()
        assert isinstance(checker._ids, OrderedDict)

    async def test_evicts_oldest_entries_not_random(self):
        """First 5000 IDs (oldest) must be removed when size exceeds 10 000."""
        checker = InMemoryIdempotencyChecker()
        # Insert 10 001 IDs in a predictable order
        for i in range(10_001):
            await checker.mark_processed(f"evt-{i:05d}")

        # After eviction: IDs 0–4999 should be gone (oldest 5000 evicted)
        for i in range(5_000):
            assert f"evt-{i:05d}" not in checker._ids, (
                f"evt-{i:05d} should have been evicted (oldest)"
            )

        # IDs 5000–10 000 must still be present
        for i in range(5_000, 10_001):
            assert f"evt-{i:05d}" in checker._ids, (
                f"evt-{i:05d} should still be tracked (newest)"
            )

    async def test_size_after_eviction_is_bounded(self):
        checker = InMemoryIdempotencyChecker()
        for i in range(10_002):
            await checker.mark_processed(f"evt-{i}")
        # After inserting 10 002 items: 10 000 triggers eviction of 5000,
        # then two more insertions → total ≤ 5002
        assert len(checker._ids) <= 5_002

    async def test_redis_mark_called_when_client_provided(self):
        redis = AsyncMock()
        checker = InMemoryIdempotencyChecker(redis_client=redis, group_name="grp")
        await checker.mark_processed("evt-x")
        redis.setex.assert_awaited_once()

    async def test_redis_is_checked_when_id_not_in_memory(self):
        redis = AsyncMock()
        redis.exists = AsyncMock(return_value=1)
        checker = InMemoryIdempotencyChecker(redis_client=redis, group_name="grp")
        result = await checker.is_processed("evt-missing-from-memory")
        assert result is True
        redis.exists.assert_awaited_once()


# ---------------------------------------------------------------------------
# EventConsumer — Fix 2 (silent drop visibility)
# ---------------------------------------------------------------------------


def _make_consumer(*, with_dlq: bool = True) -> EventConsumer:
    """Create an EventConsumer with a mocked Redis connection."""
    consumer = EventConsumer(
        redis_url="redis://localhost:6379",
        stream_name="test_stream",
        consumer_group="test_group",
    )
    consumer._redis = AsyncMock()
    if with_dlq:
        consumer._dlq = AsyncMock()
    else:
        consumer._dlq = None
    return consumer


def _flat_envelope_data(event_type: str = "user.created", event_id: str = "evt-1") -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "version": "1",
        "tenant_id": "tenant-abc",
        "timestamp": "2026-01-01T00:00:00",
        "source_service": "crm",
        "actor_id": "user-1",
        "data": json.dumps({"name": "Alice"}),
        "metadata": json.dumps({}),
    }


class TestNoHandlerLogsWarning:
    async def test_no_handler_emits_warning(self):
        consumer = _make_consumer()
        # No handlers registered
        with patch("tr_shared.events.consumer.logger") as mock_logger:
            result = await consumer._process_message("msg-1", _flat_envelope_data("order.created"))
        assert result is True  # message acknowledged
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "No handler" in warning_msg or "handler" in warning_msg.lower()

    async def test_registered_handler_does_not_warn(self):
        consumer = _make_consumer()
        consumer.register_handler("user.created", AsyncMock())
        with patch("tr_shared.events.consumer.logger") as mock_logger:
            await consumer._process_message("msg-1", _flat_envelope_data("user.created"))
        # warning should NOT have been called for no-handler
        for call in mock_logger.warning.call_args_list:
            assert "No handler" not in str(call)


def _malformed_data() -> dict:
    """Data that triggers a JSON parse error in EventEnvelope.from_flat()."""
    return {
        "event_id": "x",
        "event_type": "user.created",
        "data": "INVALID_JSON{{{",  # causes json.loads to raise
        "metadata": "{}",
    }


class TestParseFailureDLQRouting:
    async def test_malformed_message_goes_to_dlq_when_configured(self):
        consumer = _make_consumer(with_dlq=True)
        result = await consumer._process_message("msg-bad", _malformed_data())
        assert result is True
        consumer._dlq.move.assert_awaited_once()
        args = consumer._dlq.move.call_args[0]
        assert args[2] == "Malformed message"

    async def test_malformed_message_logs_error_when_no_dlq(self):
        consumer = _make_consumer(with_dlq=False)
        with patch("tr_shared.events.consumer.logger") as mock_logger:
            result = await consumer._process_message("msg-bad", _malformed_data())
        assert result is True
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args[0][0]
        assert "no DLQ" in error_msg or "DLQ" in error_msg


class TestRequeueFailureDLQFallback:
    async def test_requeue_failure_falls_back_to_dlq(self):
        consumer = _make_consumer(with_dlq=True)
        consumer._retry_policy = MagicMock()
        consumer._retry_policy.max_retries = 5
        consumer._retry_policy.delay_for = MagicMock(return_value=10)

        # Make zadd (the requeue operation) fail
        consumer._redis.zadd = AsyncMock(side_effect=ConnectionError("Redis unavailable"))

        data = _flat_envelope_data("user.created")
        handler = AsyncMock(side_effect=Exception("handler blew up"))
        consumer.register_handler("user.created", handler)

        await consumer._process_message("msg-1", data)

        # DLQ should have received the message as a requeue-failure fallback
        consumer._dlq.move.assert_awaited_once()
        reason = consumer._dlq.move.call_args[0][2]
        assert "Requeue failed" in reason
