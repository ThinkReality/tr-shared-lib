"""The two standard event paths every service uses.

publish_event: serialize a typed payload and delegate to EventProducer.publish.
parse_payload: validate an envelope's data into a typed payload at the consumer.
make_event_producer: construct a producer whose source is a Feature (invariant).

No service hand-rolls envelope/data assembly — drift becomes a type/test error.
"""

from typing import Any, TypeVar

from tr_shared.contracts.taxonomy import Feature
from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.payloads._base import EventPayload
from tr_shared.events.producer import EventProducer

P = TypeVar("P", bound=EventPayload)


def parse_payload(envelope: EventEnvelope, model: type[P]) -> P:
    """Validate ``envelope.data`` into a typed payload (raises ValidationError)."""
    return model.model_validate(envelope.data)


def make_event_producer(
    source: Feature,
    *,
    redis_url: str | None = None,
    stream_name: str = "tr_event_bus",
    maxlen: int | None = None,
) -> EventProducer:
    """Construct an EventProducer whose ``source_service`` is a Feature.

    Enforces the locked invariant: event ``source`` is ALWAYS a Feature, never a
    deployable name (``tr-crm-core``). Pass ``Feature.TASK``, not ``"task"``.
    """
    if not isinstance(source, Feature):
        raise TypeError(f"source must be a Feature, got {type(source).__name__}")
    return EventProducer(
        redis_url=redis_url,
        stream_name=stream_name,
        source_service=str(source),
        maxlen=maxlen,
    )


async def publish_event(
    producer: EventProducer,
    event_type: str,
    payload: EventPayload,
    *,
    tenant_id: str,
    actor_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> str:
    """The one standard publish path: serialize a typed payload, then delegate
    to ``EventProducer.publish``. Rejects untyped (non-EventPayload) data."""
    if not isinstance(payload, EventPayload):
        raise TypeError(
            f"payload must be an EventPayload, got {type(payload).__name__}"
        )
    return await producer.publish(
        event_type=event_type,
        tenant_id=tenant_id,
        data=payload.model_dump(mode="json"),
        actor_id=actor_id,
        metadata=metadata,
        correlation_id=correlation_id,
    )
