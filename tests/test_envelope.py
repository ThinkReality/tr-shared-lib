"""Tests for tr_shared.events.envelope."""

import json

from tr_shared.events.envelope import EventEnvelope


class TestFromFlat:
    def test_parses_all_fields(self):
        fields = {
            "event_id": "e1",
            "event_type": "listing.created",
            "version": "1.0",
            "tenant_id": "t1",
            "timestamp": "2026-01-01T00:00:00",
            "source_service": "activity-service",
            "actor_id": "a1",
            "data": json.dumps({"entity_id": "x"}),
            "metadata": json.dumps({"priority": "high"}),
        }
        env = EventEnvelope.from_flat("msg-1", fields)

        assert env.event_id == "e1"
        assert env.event_type == "listing.created"
        assert env.tenant_id == "t1"
        assert env.source_service == "activity-service"
        assert env.data == {"entity_id": "x"}
        assert env.metadata == {"priority": "high"}
        assert env.raw_message_id == "msg-1"

    def test_defaults_for_missing_fields(self):
        env = EventEnvelope.from_flat("msg-2", {})
        assert env.event_id == ""
        assert env.version == "1.0"
        assert env.data == {}
        assert env.actor_id is None

    def test_empty_actor_id_becomes_none(self):
        env = EventEnvelope.from_flat("msg-3", {"actor_id": ""})
        assert env.actor_id is None


class TestFromPayloadWrapper:
    def test_parses_wrapped_payload(self):
        payload = {
            "event_id": "e2",
            "event_type": "lead.assigned",
            "source": "notification-service",
            "tenant_id": "t2",
            "timestamp": "2026-01-01T00:00:00",
            "data": {"lead_id": "l1"},
        }
        fields = {"payload": json.dumps(payload)}
        env = EventEnvelope.from_payload_wrapper("msg-4", fields)

        assert env.event_id == "e2"
        assert env.source_service == "notification-service"
        assert env.data == {"lead_id": "l1"}

    def test_raises_on_missing_payload(self):
        import pytest

        with pytest.raises(ValueError, match="missing 'payload'"):
            EventEnvelope.from_payload_wrapper("msg-5", {})

    def test_source_service_fallback(self):
        payload = {"source_service": "svc-a"}
        fields = {"payload": json.dumps(payload)}
        env = EventEnvelope.from_payload_wrapper("msg-6", fields)
        assert env.source_service == "svc-a"
