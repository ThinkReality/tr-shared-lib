"""Tests for DeadLetterHandler."""

import json
from unittest.mock import AsyncMock, call, patch

import pytest

from tr_shared.events.dead_letter import (
    DEAD_LETTER_SUFFIX,
    DLQ_FIELD_CONSUMER_GROUP,
    DLQ_FIELD_FAILURE_REASON,
    DLQ_FIELD_ORIGINAL_DATA,
    DLQ_FIELD_ORIGINAL_MESSAGE_ID,
    DLQ_FIELD_ORIGINAL_STREAM,
    DLQ_FIELD_TIMESTAMP,
    DeadLetterHandler,
    dead_letter_stream_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handler(redis_client=None, source_stream="events:leads", consumer_group="grp", maxlen=1000):
    client = redis_client or AsyncMock()
    client.xadd = AsyncMock(return_value="12345-0")
    return DeadLetterHandler(
        redis_client=client,
        source_stream=source_stream,
        consumer_group=consumer_group,
        maxlen=maxlen,
    ), client


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestStreamNameContract:
    """The suffix + derivation are the shared producer/reader contract."""

    def test_suffix_value(self):
        assert DEAD_LETTER_SUFFIX == "_dead_letter"

    def test_dead_letter_stream_name_helper(self):
        assert dead_letter_stream_name("tr_event_bus") == "tr_event_bus_dead_letter"

    def test_handler_uses_canonical_derivation(self):
        handler, _ = _handler(source_stream="tr_event_bus")
        assert handler._dl_stream == dead_letter_stream_name("tr_event_bus")


class TestInitialization:
    def test_dl_stream_name_appends_dead_letter(self):
        handler, _ = _handler(source_stream="events:leads")
        assert handler._dl_stream == "events:leads_dead_letter"

    def test_source_stream_stored(self):
        handler, _ = _handler(source_stream="events:leads")
        assert handler._source_stream == "events:leads"

    def test_maxlen_stored(self):
        handler, _ = _handler(maxlen=500)
        assert handler._maxlen == 500


# ---------------------------------------------------------------------------
# move()
# ---------------------------------------------------------------------------

class TestMove:
    async def test_calls_xadd_once(self):
        handler, client = _handler()
        await handler.move("msg-1", {"event": "test"}, reason="parse error")
        client.xadd.assert_awaited_once()

    async def test_xadd_called_with_correct_stream(self):
        handler, client = _handler(source_stream="events:leads")
        await handler.move("msg-1", {"event": "test"}, reason="timeout")
        call_kwargs = client.xadd.call_args
        assert call_kwargs[0][0] == "events:leads_dead_letter"

    async def test_xadd_called_with_maxlen(self):
        handler, client = _handler(maxlen=250)
        await handler.move("msg-1", {}, reason="bad data")
        call_kwargs = client.xadd.call_args
        assert call_kwargs[1]["maxlen"] == 250

    async def test_entry_contains_original_message_id(self):
        handler, client = _handler()
        await handler.move("msg-abc", {"k": "v"}, reason="reason")
        entry = client.xadd.call_args[0][1]
        assert entry["original_message_id"] == "msg-abc"

    async def test_entry_contains_failure_reason(self):
        handler, client = _handler()
        await handler.move("msg-1", {}, reason="deserialization error")
        entry = client.xadd.call_args[0][1]
        assert entry["failure_reason"] == "deserialization error"

    async def test_entry_contains_json_encoded_original_data(self):
        handler, client = _handler()
        data = {"key": "value", "num": "42"}
        await handler.move("msg-1", data, reason="test")
        entry = client.xadd.call_args[0][1]
        parsed = json.loads(entry["original_data"])
        assert parsed == data

    async def test_entry_contains_timestamp(self):
        handler, client = _handler()
        await handler.move("msg-1", {}, reason="test")
        entry = client.xadd.call_args[0][1]
        assert "timestamp" in entry
        float(entry["timestamp"])

    async def test_entry_contains_consumer_group(self):
        handler, client = _handler(consumer_group="my-group")
        await handler.move("msg-1", {}, reason="test")
        entry = client.xadd.call_args[0][1]
        assert entry["consumer_group"] == "my-group"

    async def test_entry_keys_match_field_constants(self):
        handler, client = _handler()
        await handler.move("msg-1", {"k": "v"}, reason="test")
        entry = client.xadd.call_args[0][1]
        assert set(entry.keys()) == {
            DLQ_FIELD_ORIGINAL_MESSAGE_ID,
            DLQ_FIELD_ORIGINAL_STREAM,
            DLQ_FIELD_CONSUMER_GROUP,
            DLQ_FIELD_FAILURE_REASON,
            DLQ_FIELD_TIMESTAMP,
            DLQ_FIELD_ORIGINAL_DATA,
        }

    async def test_original_stream_equals_source_stream(self):
        handler, client = _handler(source_stream="tr_event_bus")
        await handler.move("msg-1", {}, reason="test")
        entry = client.xadd.call_args[0][1]
        assert entry[DLQ_FIELD_ORIGINAL_STREAM] == "tr_event_bus"

    async def test_redis_failure_is_swallowed(self):
        client = AsyncMock()
        client.xadd = AsyncMock(side_effect=Exception("Redis down"))
        handler, _ = _handler(redis_client=client)
        await handler.move("msg-1", {}, reason="test")

    async def test_redis_failure_does_not_reraise(self):
        client = AsyncMock()
        client.xadd = AsyncMock(side_effect=ConnectionError("Connection refused"))
        handler, _ = _handler(redis_client=client)
        try:
            await handler.move("msg-1", {}, reason="test")
        except Exception:
            pytest.fail("move() should not re-raise Redis errors")
