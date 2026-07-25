"""Typed payloads for listing.* events (tr-content-platform listing module).

Two emitters, one file: the audit path (status changes) and the permit-expiry
beat. All ids are str (UUIDs stringified at emit); dates are ISO str.
"""

from typing import Any

from tr_shared.events.payloads._base import EventPayload


class ListingPermitEventV1(EventPayload):
    """listing.permit_expired / listing.permit_expiring (identical shape).

    Emitted per (permit, recipient) by the daily permit-expiry watcher.
    ``days_until_expiry`` is negative once the permit has lapsed.

    Field set mirrors
    app/modules/listing/services/listings/permit_expiry_service.py. ``listing_id``
    is what the notification templates interpolate; ``entity_type``/``entity_id``
    are what the crm-core consumer reads to link the notification to a record —
    different readers, so both are carried.
    """

    entity_id: str
    entity_type: str
    listing_id: str
    permit_number: str
    permit_type: str | None = None
    expires_at: str
    days_until_expiry: int
    notification_recipient_id: str | None = None


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
