import json
import uuid

import pytest
import redis

from tr_shared.contracts.taxonomy import Feature
from tr_shared.events.producer import EventProducer

pytestmark = pytest.mark.integration


@pytest.fixture
def stream(redis_url):
    inspector = redis.Redis.from_url(redis_url, decode_responses=True)
    name = f"itest:{uuid.uuid4().hex}"
    yield name, inspector
    inspector.delete(name)
    inspector.close()


@pytest.fixture
async def producer(redis_url, stream):
    name, _inspector = stream
    p = EventProducer(redis_url=redis_url, stream_name=name, source_service=Feature.LISTING)
    yield p
    await p.disconnect()


def _entries(stream) -> list[tuple[str, dict[str, str]]]:
    name, inspector = stream
    return inspector.xrange(name)


async def test_the_envelope_carries_nine_fields(producer, stream):
    event_id = await producer.publish("listing.created", "t1", {"entity_id": "e1"})

    [(_id, envelope)] = _entries(stream)
    assert set(envelope) == {
        "event_id",
        "event_type",
        "version",
        "tenant_id",
        "timestamp",
        "source_service",
        "actor_id",
        "data",
        "metadata",
    }
    assert envelope["event_id"] == event_id
    assert envelope["event_type"] == "listing.created"
    assert envelope["source_service"] == "listing"
    assert envelope["version"] == "1.0"
    assert json.loads(envelope["data"]) == {"entity_id": "e1"}


async def test_the_correlation_id_travels_in_the_metadata(producer, stream):
    await producer.publish("x", "t1", {}, correlation_id="corr-1")

    [(_id, envelope)] = _entries(stream)
    assert json.loads(envelope["metadata"])["correlation_id"] == "corr-1"


async def test_strict_mode_publishes_when_the_entity_fields_are_present(producer, stream):
    data = {"entity_id": "e1", "entity_type": "listing", "action": "create"}

    await producer.publish("x", "t1", data, strict_mode=True)

    assert len(_entries(stream)) == 1


async def test_the_stream_is_trimmed_towards_maxlen(redis_url, stream):
    name, inspector = stream
    published = 250
    p = EventProducer(redis_url=redis_url, stream_name=name, source_service=Feature.TASK, maxlen=1)
    try:
        for _ in range(published):
            await p.publish("x", "t1", {})
    finally:
        await p.disconnect()

    assert inspector.xlen(name) < published
