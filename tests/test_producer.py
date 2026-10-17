"""Tests for tr_shared.events.producer."""

import pytest

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


UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"


class TestPublishWithoutRedis:
    async def test_strict_mode_requires_entity_fields(self):
        p = EventProducer(redis_url=UNREACHABLE_REDIS_URL, source_service=Feature.TASK)
        with pytest.raises(ValueError, match="entity_id"):
            await p.publish("x", "t1", {}, strict_mode=True)

    async def test_raises_when_redis_unavailable(self):
        p = EventProducer(stream_name="s", source_service=Feature.TASK)
        with pytest.raises(RuntimeError, match="not available"):
            await p.publish("x", "t1", {})

    async def test_redis_failure_translated_to_transport_error(self):
        p = EventProducer(redis_url=UNREACHABLE_REDIS_URL, source_service=Feature.LISTING)
        try:
            with pytest.raises(EventPublishTransportError):
                await p.publish("listing.created", "t1", {})
        finally:
            await p.disconnect()

    async def test_programming_error_propagates_raw(self):
        p = EventProducer(redis_url=UNREACHABLE_REDIS_URL, source_service=Feature.LISTING)
        with pytest.raises(TypeError):
            await p.publish("listing.created", "t1", {"when": object()})
