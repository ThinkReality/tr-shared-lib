"""Typed payloads for listing.* events (tr-content-platform listing module).

Scoped to the PropertyFinder-keyed lifecycle events that are emitted by a SINGLE
path (the ListingEventPublisher domain methods, from webhook_tasks) — these have
one unambiguous shape. The status-change events (created/updated/verified/…) are
emitted by BOTH the domain path and the audit path with different shapes and are
intentionally NOT modelled here yet (they need emitter canonicalisation first).

Field set mirrors the dict built in
app/modules/listing/services/events/event_publisher.py:emit_listing_*. All ids
are str (UUIDs stringified at emit); prices are float; dates are ISO str.
"""

from tr_shared.events.payloads._base import EventPayload


class ListingPfEventV1(EventPayload):
    """Common fields for the PropertyFinder-keyed listing lifecycle events."""

    listing_id: str
    pf_listing_id: str
    notification_recipient_id: str | None = None


class ListingSaleV1(ListingPfEventV1):
    """listing.sold / listing.rented (identical shape — rented reuses ``sold_price``)."""

    sold_price: float | None = None
    transaction_date: str | None = None


class ListingExpiredV1(ListingPfEventV1):
    """listing.expired."""

    expiry_reason: str | None = None


class ListingRepublishedV1(ListingPfEventV1):
    """listing.republished."""

    repost_type: str | None = None
    new_expiry: str | None = None


class ListingDeletedV1(ListingPfEventV1):
    """listing.deleted (base fields only)."""
