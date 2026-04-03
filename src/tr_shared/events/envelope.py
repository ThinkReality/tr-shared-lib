"""Canonical event envelope used by both producer and consumer."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EventEnvelope:
    """Standard event envelope for the ThinkRealty event bus.

    All events on ``tr_event_bus`` use flat Redis hash fields.
    The producer writes these fields; the consumer reads them.
    """

    event_id: str
    event_type: str
    version: str
    tenant_id: str
    timestamp: str
    source_service: str
    actor_id: str | None
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_message_id: str = ""

    @classmethod
    def from_flat(cls, message_id: str, fields: dict[str, str]) -> "EventEnvelope":
        """Create from flat Redis Stream hash fields (Activity format)."""
        import json

        return cls(
            event_id=fields.get("event_id", ""),
            event_type=fields.get("event_type", ""),
            version=fields.get("version", "1.0"),
            tenant_id=fields.get("tenant_id", ""),
            timestamp=fields.get("timestamp", ""),
            source_service=fields.get("source_service", ""),
            actor_id=fields.get("actor_id") or None,
            data=json.loads(fields.get("data", "{}")),
            metadata=json.loads(fields.get("metadata", "{}")),
            raw_message_id=message_id,
        )

    @classmethod
    def from_payload_wrapper(cls, message_id: str, fields: dict[str, str]) -> "EventEnvelope":
        """Create from payload-wrapped format (legacy Notification format)."""
        import json

        payload_str = fields.get("payload")
        if not payload_str:
            msg = "Message missing 'payload' field"
            raise ValueError(msg)

        payload = json.loads(payload_str)
        return cls(
            event_id=payload.get("event_id", ""),
            event_type=payload.get("event_type", ""),
            version=payload.get("version", "1.0"),
            tenant_id=payload.get("tenant_id", ""),
            timestamp=payload.get("timestamp", ""),
            source_service=payload.get("source", payload.get("source_service", "")),
            actor_id=payload.get("actor_id"),
            data=payload.get("data", {}),
            metadata=payload.get("metadata", {}),
            raw_message_id=message_id,
        )
