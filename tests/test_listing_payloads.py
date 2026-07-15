"""Round-trip + strictness tests for listing.* PF-lifecycle payloads.

The dicts below mirror exactly what
app/modules/listing/services/events/event_publisher.py emits for each event.
"""

import pytest
from pydantic import ValidationError

from tr_shared.events.envelope import EventEnvelope
from tr_shared.events.helpers import parse_payload
from tr_shared.events.payloads.listing import (
    ListingDeletedV1,
    ListingExpiredV1,
    ListingRepublishedV1,
    ListingSaleV1,
)


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


_SALE = {
    "listing_id": "l1",
    "pf_listing_id": "pf1",
    "sold_price": 100.0,
    "transaction_date": "2026-01-01",
    "notification_recipient_id": "u1",
}
_EXPIRED = {
    "listing_id": "l1",
    "pf_listing_id": "pf1",
    "expiry_reason": "delisted",
    "notification_recipient_id": None,
}
_REPUB = {
    "listing_id": "l1",
    "pf_listing_id": "pf1",
    "repost_type": "manual",
    "new_expiry": "2026-02-01",
    "notification_recipient_id": None,
}
_DELETED = {"listing_id": "l1", "pf_listing_id": "pf1", "notification_recipient_id": None}


@pytest.mark.parametrize(
    ("event_type", "data", "model"),
    [
        ("listing.sold", _SALE, ListingSaleV1),
        ("listing.rented", _SALE, ListingSaleV1),  # rented reuses the sold shape
        ("listing.expired", _EXPIRED, ListingExpiredV1),
        ("listing.republished", _REPUB, ListingRepublishedV1),
        ("listing.deleted", _DELETED, ListingDeletedV1),
    ],
)
def test_roundtrip_matches_emitted_dict(event_type, data, model):
    parsed = parse_payload(_env(event_type, data), model)
    assert parsed.model_dump() == data


def test_extra_key_rejected():
    with pytest.raises(ValidationError):
        ListingSaleV1(listing_id="l1", pf_listing_id="pf1", bogus="x")


def test_required_keys_enforced():
    with pytest.raises(ValidationError):
        ListingDeletedV1(listing_id="l1")


def test_optionals_default_to_none():
    p = ListingDeletedV1(listing_id="l1", pf_listing_id="pf1")
    assert p.notification_recipient_id is None
