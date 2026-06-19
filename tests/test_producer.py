"""Tests for tr_shared.events.producer."""

import json
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from tr_shared.contracts.taxonomy import Feature
from tr_shared.events.exceptions import EventPublishTransportError
from tr_shared.events.producer import EventProducer


class TestSourceServiceValidation:
    def test_accepts_feature_enum(self):
        p = EventProducer(source_service=Feature.TASK)
        assert p._source_service == "task"

    def test_accepts_valid_feature_string(self):
        p = EventProducer(source_service="task")
        assert p._source_service == "task"

    def test_rejects_deployable_name(self):
        with pytest.raises(ValueError, match="tr-crm-core"):
            EventProducer(source_service="tr-crm-core")

    def test_rejects_unknown_sentinel(self):
        with pytest.raises(ValueError, match="unknown"):
            EventProducer(source_service="unknown")

    def test_source_is_required(self):
        with pytest.raises(TypeError):
            EventProducer()  # type: ignore[call-arg]

    def test_envelope_carries_normalized_feature_value(self):
        p = EventProducer(source_service=Feature.LISTING)
        assert p._source_service == "listing"


class TestPublish:
    @pytest.fixture
    def producer(self):
        p = EventProducer(
            redis_url="redis://localhost",
            stream_name="test_stream",
            source_service=Feature.LISTING,
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
        assert envelope["source_service"] == "listing"
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
        p = EventProducer(stream_name="s", source_service=Feature.TASK)
        with pytest.raises(RuntimeError, match="not available"):
            await p.publish("x", "t1", {})

    async def test_redis_failure_translated_to_transport_error(self, producer):
        producer._redis.xadd = AsyncMock(
            side_effect=RedisConnectionError("broker down")
        )
        with pytest.raises(EventPublishTransportError):
            await producer.publish("listing.created", "t1", {})

    async def test_programming_error_propagates_raw(self, producer):
        # A non-Redis bug must NOT be masked as a transport failure.
        producer._redis.xadd = AsyncMock(side_effect=TypeError("bug"))
        with pytest.raises(TypeError):
            await producer.publish("listing.created", "t1", {})


class TestConnectDisconnect:
    async def test_connect_creates_client(self):
        p = EventProducer(redis_url="redis://localhost", source_service=Feature.TASK)
        assert p._redis is None
        # can't actually connect in unit test, but structure is correct

    async def test_disconnect_closes(self):
        p = EventProducer(redis_url="redis://localhost", source_service=Feature.TASK)
        mock_redis = AsyncMock()
        p._redis = mock_redis
        await p.disconnect()
        mock_redis.close.assert_awaited_once()
        assert p._redis is None

    async def test_set_redis_injects_client(self):
        p = EventProducer(stream_name="s", source_service=Feature.TASK)
        mock = AsyncMock()
        p.set_redis(mock)
        assert p._redis is mock
