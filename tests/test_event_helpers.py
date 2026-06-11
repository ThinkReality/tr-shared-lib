# tests/test_event_helpers.py
import pytest
from pydantic import ValidationError

from tr_shared.contracts.taxonomy import Feature
from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.helpers import make_event_producer, parse_payload, publish_event
from tr_shared.events.payloads.task import TaskCreatedV1
from tr_shared.events.producer import EventProducer

_PAYLOAD = TaskCreatedV1(
    task_id="t1", title="x", status="open", priority="high",
    entity_type="lead", entity_id="e1", assigned_to="u1", action="created",
)


def _envelope(data: dict) -> EventEnvelope:
    return EventEnvelope(
        event_id="e", event_type="task.created", version="1.0", tenant_id="ten1",
        timestamp="2026-01-01T00:00:00Z", source_service="task", actor_id=None,
        data=data,
    )


def test_parse_payload_roundtrip():
    parsed = parse_payload(_envelope(_PAYLOAD.model_dump()), TaskCreatedV1)
    assert parsed == _PAYLOAD


def test_parse_payload_rejects_missing_fields():
    with pytest.raises(ValidationError):
        parse_payload(_envelope({"task_id": "t1"}), TaskCreatedV1)


class _RecordingProducer:
    """Duck-typed stand-in for EventProducer — records publish() kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "evt-123"


async def test_publish_event_serializes_typed_payload():
    prod = _RecordingProducer()
    evt_id = await publish_event(
        prod, "task.created", _PAYLOAD, tenant_id="ten1", actor_id="a1",
    )
    assert evt_id == "evt-123"
    call = prod.calls[0]
    assert call["event_type"] == "task.created"
    assert call["tenant_id"] == "ten1"
    assert call["actor_id"] == "a1"
    assert call["data"]["task_id"] == "t1"
    assert call["data"]["action"] == "created"


async def test_publish_event_rejects_untyped_payload():
    prod = _RecordingProducer()
    with pytest.raises(TypeError):
        await publish_event(prod, "task.created", {"task_id": "t1"}, tenant_id="ten1")


def test_make_event_producer_requires_a_feature():
    with pytest.raises(TypeError):
        make_event_producer("task")  # raw string is not a Feature


def test_make_event_producer_sets_source_to_the_feature_value():
    prod = make_event_producer(Feature.TASK)
    assert isinstance(prod, EventProducer)
    assert prod._source_service == "task"


def test_helpers_and_payload_base_exported_from_events_package():
    from tr_shared.events import (
        EventPayload,
        make_event_producer,
        parse_payload,
        publish_event,
    )

    # The export surface is the contract — assert the names resolve, not a pinned
    # version literal (which rots on every bump).
    assert callable(make_event_producer)
    assert callable(parse_payload)
    assert callable(publish_event)
    assert isinstance(EventPayload, type)
