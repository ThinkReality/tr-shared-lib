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

from typing import Any

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


class ListingAuditEventV1(EventPayload):
    """Single generic model for the 13 audit-path listing.* events.

    Covers listing.{created,updated,price_changed,owner_changed,verified,rejected,
    resubmitted,document_submitted,publish_requested,published,unpublished,
    archived,refreshed} — these are shape-identical, differing only by the
    envelope event_type and the ``action`` value. The legacy emit dict also
    injected a redundant ``event_type`` key into ``data``; that key is dropped
    here (extra="forbid" rejects it).

    Field set mirrors
    app/modules/listing/services/listings/listing_audit_service.py base_data.
    ``entity_type`` is retained — crm-core notification + activity-logger
    consumers read it for entity linking.
    """

    entity_id: str
    entity_type: str
    action: str
    new_status: str | None = None
    old_status: str | None = None
    new_verification_state: str | None = None
    old_verification_state: str | None = None
    changes: dict[str, Any] | None = None
    notification_recipient_id: str | None = None
