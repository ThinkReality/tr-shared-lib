"""Tests for the Redis monitoring buffer helpers."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tr_shared.monitoring.redis_buffer import (
    BUFFER_TTL_SECONDS,
    flush_buffer_sync,
    get_buffer_key,
    push_to_buffer,
)


class TestGetBufferKey:
    def test_returns_formatted_key(self):
        key = get_buffer_key("crm-backend")
        assert key == "monitoring:buffer:crm-backend"

    def test_includes_service_name(self):
        key = get_buffer_key("tr-listing-service")
        assert "tr-listing-service" in key

    def test_different_services_produce_different_keys(self):
        assert get_buffer_key("svc-a") != get_buffer_key("svc-b")


class TestPushToBuffer:
    async def test_calls_rpush_with_json_payload(self):
        redis = AsyncMock()
        await push_to_buffer(redis, "svc", {"status": 200, "ms": 50})
        redis.rpush.assert_awaited_once()
        key, payload = redis.rpush.call_args[0]
        assert key == "monitoring:buffer:svc"
        parsed = json.loads(payload)
        assert parsed["status"] == 200

    async def test_sets_ttl_after_push(self):
        redis = AsyncMock()
        await push_to_buffer(redis, "svc", {"x": 1})
        redis.expire.assert_awaited_once_with(
            "monitoring:buffer:svc", BUFFER_TTL_SECONDS
        )

    async def test_swallows_redis_rpush_error(self):
        redis = AsyncMock()
        redis.rpush.side_effect = Exception("connection refused")
        await push_to_buffer(redis, "svc", {"x": 1})  # Must not raise

    async def test_swallows_redis_expire_error(self):
        redis = AsyncMock()
        redis.expire.side_effect = Exception("timeout")
        await push_to_buffer(redis, "svc", {"x": 1})  # Must not raise

    async def test_serializes_non_json_types_with_default_str(self):
        from datetime import datetime
        redis = AsyncMock()
        await push_to_buffer(redis, "svc", {"ts": datetime(2026, 1, 1)})
        _, payload = redis.rpush.call_args[0]
        assert "2026-01-01" in payload


class TestFlushBufferSync:
    def test_returns_list_of_parsed_records(self):
        pipe = MagicMock()
        pipe.execute.return_value = [
            json.dumps({"status": 200}),
            json.dumps({"status": 404}),
            None,
        ]
        redis = MagicMock()
        redis.pipeline.return_value = pipe

        result = flush_buffer_sync(redis, "svc", batch_size=3)
        assert len(result) == 2
        assert result[0]["status"] == 200

    def test_stops_at_first_none(self):
        pipe = MagicMock()
        pipe.execute.return_value = [
            json.dumps({"a": 1}),
            None,
            json.dumps({"b": 2}),  # This should never be reached
        ]
        redis = MagicMock()
        redis.pipeline.return_value = pipe

        result = flush_buffer_sync(redis, "svc")
        assert len(result) == 1

    def test_skips_malformed_json(self):
        pipe = MagicMock()
        pipe.execute.return_value = ["not-json", None]
        redis = MagicMock()
        redis.pipeline.return_value = pipe

        result = flush_buffer_sync(redis, "svc")
        assert result == []

    def test_returns_empty_list_on_redis_error(self):
        redis = MagicMock()
        redis.pipeline.side_effect = Exception("broken")
        result = flush_buffer_sync(redis, "svc")
        assert result == []

    def test_uses_correct_batch_size_for_lpop(self):
        pipe = MagicMock()
        pipe.execute.return_value = [None] * 7
        redis = MagicMock()
        redis.pipeline.return_value = pipe

        flush_buffer_sync(redis, "svc", batch_size=7)
        assert pipe.lpop.call_count == 7
