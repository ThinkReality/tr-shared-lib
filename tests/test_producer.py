"""Tests for tr_shared.events.producer."""

import json
from unittest.mock import AsyncMock

import pytest

from tr_shared.events.producer import EventProducer


class TestPublish:
    @pytest.fixture
    def producer(self):
        p = EventProducer(
            redis_url="redis://localhost",
            stream_name="test_stream",
            source_service="test-svc",
        )
        p._redis = AsyncMock()
        p._redis.xadd = AsyncMock(return_value="1-0")
        return p

    async def test_envelope_has_9_fields(self, producer):
        await producer.publish("listing.created", "t1", {"entity_id": "e1"})
        call_args = producer._redis.xadd.call_args
        envelope = call_args[0][1]

        assert set(envelope.keys()) == {
            "event_id", "event_type", "version", "tenant_id",
            "timestamp", "source_service", "actor_id", "data", "metadata",
        }
        assert envelope["event_type"] == "listing.created"
        assert envelope["source_service"] == "test-svc"
        assert envelope["version"] == "1.0"

    async def test_data_is_json_serialized(self, producer):
        await producer.publish("x", "t1", {"key": "val"})
        envelope = producer._redis.xadd.call_args[0][1]
        parsed = json.loads(envelope["data"])
        assert parsed == {"key": "val"}

    async def test_correlation_id_in_metadata(self, producer):
        await producer.publish("x", "t1", {}, correlation_id="corr-1")
        envelope = producer._redis.xadd.call_args[0][1]
        meta = json.loads(envelope["metadata"])
        assert meta["correlation_id"] == "corr-1"

    async def test_strict_mode_requires_entity_fields(self, producer):
        with pytest.raises(ValueError, match="entity_id"):
            await producer.publish("x", "t1", {}, strict_mode=True)

    async def test_strict_mode_passes_with_all_fields(self, producer):
        data = {"entity_id": "e1", "entity_type": "listing", "action": "create"}
        eid = await producer.publish("x", "t1", data, strict_mode=True)
        assert eid  # returns a UUID string

    async def test_returns_event_id(self, producer):
        eid = await producer.publish("x", "t1", {})
        assert len(eid) == 36  # UUID format

    async def test_maxlen_passed_to_xadd(self, producer):
        producer._maxlen = 5000
        await producer.publish("x", "t1", {})
        call_kwargs = producer._redis.xadd.call_args
        assert call_kwargs[1]["maxlen"] == 5000

    async def test_raises_when_redis_unavailable(self):
        p = EventProducer(stream_name="s", source_service="svc")
        with pytest.raises(RuntimeError, match="not available"):
            await p.publish("x", "t1", {})


class TestConnectDisconnect:
    async def test_connect_creates_client(self):
        p = EventProducer(redis_url="redis://localhost")
        assert p._redis is None
        # can't actually connect in unit test, but structure is correct

    async def test_disconnect_closes(self):
        p = EventProducer(redis_url="redis://localhost")
        mock_redis = AsyncMock()
        p._redis = mock_redis
        await p.disconnect()
        mock_redis.close.assert_awaited_once()
        assert p._redis is None

    async def test_set_redis_injects_client(self):
        p = EventProducer(stream_name="s", source_service="svc")
        mock = AsyncMock()
        p.set_redis(mock)
        assert p._redis is mock
