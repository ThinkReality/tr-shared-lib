"""Round-trip + strictness tests for the listing.* payloads.

The dicts below mirror exactly what tr-content-platform emits:
- permit events: services/listings/permit_expiry_service.py
- audit events:  services/listings/listing_audit_service.py
"""

import pytest
from pydantic import ValidationError

from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.event_types import ListingEvents
from tr_shared.events.helpers import parse_payload
from tr_shared.events.payloads.listing import ListingPermitEventV1


def _env(event_type: str, data: dict) -> EventEnvelope:
    return EventEnvelope(
        event_id="e",
        event_type=event_type,
        version="1.0",
        tenant_id="ten1",
        timestamp="2026-01-01T00:00:00Z",
        source_service="listing",
        actor_id=None,
        data=data,
    )


_EXPIRED = {
    "entity_id": "l1",
    "entity_type": "listing",
    "listing_id": "l1",
    "permit_number": "20250000537099",
    "permit_type": "rera",
    "expires_at": "2026-01-01T00:00:00+00:00",
    "days_until_expiry": -3,
    "notification_recipient_id": "u1",
}
_EXPIRING = {**_EXPIRED, "days_until_expiry": 7}


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        (ListingEvents.PERMIT_EXPIRED, _EXPIRED),
        (ListingEvents.PERMIT_EXPIRING, _EXPIRING),
    ],
)
def test_roundtrip_matches_emitted_dict(event_type, data):
    parsed = parse_payload(_env(event_type, data), ListingPermitEventV1)
    assert parsed.model_dump() == data


def test_extra_key_rejected():
    with pytest.raises(ValidationError):
        ListingPermitEventV1(**_EXPIRED, bogus="x")


def test_required_keys_enforced():
    incomplete = {k: v for k, v in _EXPIRED.items() if k != "permit_number"}
    with pytest.raises(ValidationError):
        ListingPermitEventV1(**incomplete)


def test_optionals_default_to_none():
    payload = ListingPermitEventV1(
        **{k: v for k, v in _EXPIRED.items() if k not in ("permit_type", "notification_recipient_id")}
    )
    assert payload.permit_type is None
    assert payload.notification_recipient_id is None
