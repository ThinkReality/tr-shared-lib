"""Tests for InMemoryIdempotencyChecker and EventConsumer silent-drop fixes."""

import json
from collections import OrderedDict
from unittest.mock import AsyncMock, patch

from tr_shared.events.consumer import EventConsumer, InMemoryIdempotencyChecker
from tr_shared.events.dead_letter import DeadLetterHandler, dead_letter_stream_name
from tr_shared.events.retry_policy import RetryPolicy
from tr_shared.events.retry_state import RetryStateStore


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


def _make_consumer(*, with_dlq: bool = True) -> EventConsumer:
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
        with patch("tr_shared.events.consumer.logger") as mock_logger:
            result = await consumer._process_message("msg-1", _flat_envelope_data("order.created"))
        assert result == (True, True)  # acknowledged, no retry
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "No handler" in warning_msg or "handler" in warning_msg.lower()

    async def test_registered_handler_does_not_warn(self):
        consumer = _make_consumer()
        consumer.register_handler("user.created", AsyncMock())
        with patch("tr_shared.events.consumer.logger") as mock_logger:
            await consumer._process_message("msg-1", _flat_envelope_data("user.created"))
        for call in mock_logger.warning.call_args_list:
            assert "No handler" not in str(call)


def _malformed_data() -> dict:
    """Data that triggers a JSON parse error in EventEnvelope.from_flat()."""
    return {
        "event_id": "x",
        "event_type": "user.created",
        "data": "INVALID_JSON{{{",
        "metadata": "{}",
    }


class TestParseFailureDLQRouting:
    async def test_malformed_message_goes_to_dlq_when_configured(self):
        consumer = _make_consumer(with_dlq=True)
        result = await consumer._process_message("msg-bad", _malformed_data())
        assert result == (True, True)
        consumer._dlq.move.assert_awaited_once()
        args = consumer._dlq.move.call_args[0]
        assert args[2] == "Malformed message"

    async def test_malformed_message_logs_error_when_no_dlq(self):
        consumer = _make_consumer(with_dlq=False)
        with patch("tr_shared.events.consumer.logger") as mock_logger:
            result = await consumer._process_message("msg-bad", _malformed_data())
        assert result == (True, True)
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args[0][0]
        assert "no DLQ" in error_msg or "DLQ" in error_msg


class TestHandlerFailureReturnsAckSignal:
    """The (handler_ok, should_ack) contract driving the PEL retry path."""

    def _failing_consumer(self, *, max_retries: int) -> EventConsumer:
        consumer = _make_consumer(with_dlq=True)
        consumer._retry_policy = RetryPolicy(max_retries=max_retries)
        consumer._retry_state = AsyncMock()
        consumer.register_handler("user.created", AsyncMock(side_effect=Exception("boom")))
        return consumer

    async def test_below_max_retries_leaves_in_pel(self):
        consumer = self._failing_consumer(max_retries=3)
        consumer._retry_state.increment = AsyncMock(return_value=1)
        result = await consumer._process_message("msg-1", _flat_envelope_data("user.created"))
        assert result == (False, False)  # not acked → stays in PEL
        consumer._dlq.move.assert_not_awaited()

    async def test_at_max_retries_moves_to_dlq_and_acks(self):
        consumer = self._failing_consumer(max_retries=3)
        consumer._retry_state.increment = AsyncMock(return_value=3)
        result = await consumer._process_message("msg-1", _flat_envelope_data("user.created"))
        assert result == (False, True)  # acked → leaves PEL
        consumer._dlq.move.assert_awaited_once()
        assert "Max retries exceeded" in consumer._dlq.move.call_args[0][2]
        consumer._retry_state.clear.assert_awaited_once()

    async def test_retry_state_failure_routes_to_dlq(self):
        consumer = self._failing_consumer(max_retries=3)
        consumer._retry_state.increment = AsyncMock(side_effect=ConnectionError("redis down"))
        result = await consumer._process_message("msg-1", _flat_envelope_data("user.created"))
        assert result == (False, True)  # fail-safe: straight to DLQ
        consumer._dlq.move.assert_awaited_once()

    async def test_success_clears_retry_state_and_acks(self):
        consumer = _make_consumer(with_dlq=True)
        consumer._retry_state = AsyncMock()
        consumer.register_handler("user.created", AsyncMock())
        result = await consumer._process_message("msg-1", _flat_envelope_data("user.created"))
        assert result == (True, True)
        consumer._retry_state.clear.assert_awaited_once_with("msg-1")


# ── PEL retry + crash-orphan recovery (fakeredis-backed, real stream engine) ──

STREAM = "s"
GROUP = "g"


async def _stream_consumer(fake_redis, *, max_retries=3, claim_min_idle_ms=0, zombie_idle_ms=86_400_000):
    consumer = EventConsumer(
        redis_url="redis://unused",
        stream_name=STREAM,
        consumer_group=GROUP,
        consumer_name="c1",
        retry_policy=RetryPolicy(max_retries=max_retries),
        claim_min_idle_ms=claim_min_idle_ms,
        zombie_idle_ms=zombie_idle_ms,
    )
    consumer._redis = fake_redis
    consumer._dlq = DeadLetterHandler(fake_redis, STREAM, GROUP)
    consumer._retry_state = RetryStateStore(fake_redis, STREAM, GROUP)
    await consumer._ensure_consumer_group()
    return consumer


async def _read_and_process(consumer, fake_redis, consumer_name="c1"):
    """One `>` read + process pass (mirrors _consume_loop body)."""
    msgs = await fake_redis.xreadgroup(
        groupname=GROUP, consumername=consumer_name, streams={STREAM: ">"}, count=10
    )
    for _stream, entries in msgs or []:
        for msg_id, msg_data in entries:
            _ok, should_ack = await consumer._process_message(msg_id, msg_data)
            if should_ack:
                await consumer._ack(msg_id)


class TestPelRetryAndOrphanRecovery:
    async def test_failed_handler_keeps_message_in_pel(self, async_fake_redis):
        consumer = await _stream_consumer(async_fake_redis, max_retries=3)
        consumer.register_handler("user.created", AsyncMock(side_effect=Exception("boom")))
        await async_fake_redis.xadd(STREAM, _flat_envelope_data("user.created"))

        await _read_and_process(consumer, async_fake_redis)

        pending = await async_fake_redis.xpending(STREAM, GROUP)
        assert pending["pending"] == 1  # left in PEL, not acked

    async def test_no_new_stream_entry_on_retry(self, async_fake_redis):
        consumer = await _stream_consumer(async_fake_redis, max_retries=3)
        consumer.register_handler("user.created", AsyncMock(side_effect=Exception("boom")))
        await async_fake_redis.xadd(STREAM, _flat_envelope_data("user.created"))

        await _read_and_process(consumer, async_fake_redis)
        await consumer._claim_once()  # a retry cycle

        assert await async_fake_redis.xlen(STREAM) == 1  # no XADD storm

    async def test_claimer_reclaims_and_succeeds_on_retry(self, async_fake_redis):
        consumer = await _stream_consumer(async_fake_redis, max_retries=3, claim_min_idle_ms=0)
        handler = AsyncMock(side_effect=[Exception("boom"), None])  # fail once, then succeed
        consumer.register_handler("user.created", handler)
        await async_fake_redis.xadd(STREAM, _flat_envelope_data("user.created"))

        await _read_and_process(consumer, async_fake_redis)  # attempt 1 fails → PEL
        claimed = await consumer._claim_once()  # attempt 2 succeeds → acked

        assert claimed == 1
        assert handler.await_count == 2
        pending = await async_fake_redis.xpending(STREAM, GROUP)
        assert pending["pending"] == 0

    async def test_claimer_recovers_crash_orphan(self, async_fake_redis):
        consumer = await _stream_consumer(async_fake_redis, max_retries=3, claim_min_idle_ms=0)
        handler = AsyncMock()  # succeeds
        consumer.register_handler("user.created", handler)
        await async_fake_redis.xadd(STREAM, _flat_envelope_data("user.created"))

        # A now-dead consumer reads it and never acks (crash between read and ack).
        await async_fake_redis.xreadgroup(
            groupname=GROUP, consumername="dead-worker", streams={STREAM: ">"}, count=10
        )
        pending_before = await async_fake_redis.xpending(STREAM, GROUP)
        assert pending_before["pending"] == 1

        claimed = await consumer._claim_once()  # c1 reclaims from dead-worker

        assert claimed == 1
        handler.assert_awaited_once()
        pending_after = await async_fake_redis.xpending(STREAM, GROUP)
        assert pending_after["pending"] == 0

    async def test_max_retries_moves_to_dlq_and_acks(self, async_fake_redis):
        consumer = await _stream_consumer(async_fake_redis, max_retries=1, claim_min_idle_ms=0)
        consumer.register_handler("user.created", AsyncMock(side_effect=Exception("always")))
        await async_fake_redis.xadd(STREAM, _flat_envelope_data("user.created"))

        await _read_and_process(consumer, async_fake_redis)  # attempt 1 == max → DLQ + ack

        pending = await async_fake_redis.xpending(STREAM, GROUP)
        assert pending["pending"] == 0
        assert await async_fake_redis.xlen(dead_letter_stream_name(STREAM)) == 1

    async def test_sweep_deletes_only_empty_idle_others(self):
        """Sweep decision logic — deterministic (mocked xinfo, no sub-ms timing).
        Real-timing behaviour is covered by the real-Redis integration test."""
        consumer = _make_consumer()
        consumer._consumer_name = "c1"
        consumer._zombie_idle_ms = 1_000
        consumer._redis.xinfo_consumers = AsyncMock(
            return_value=[
                {"name": "zombie", "pending": 0, "idle": 5_000},   # empty + idle → swept
                {"name": "busy", "pending": 3, "idle": 9_999},     # has pending → kept
                {"name": "fresh", "pending": 0, "idle": 100},      # too recent → kept
                {"name": "c1", "pending": 0, "idle": 9_999},       # self → kept
            ]
        )
        consumer._redis.xgroup_delconsumer = AsyncMock()

        await consumer._sweep_zombie_consumers()

        deleted = [c.args[2] for c in consumer._redis.xgroup_delconsumer.call_args_list]
        assert deleted == ["zombie"]
