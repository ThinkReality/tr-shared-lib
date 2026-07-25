"""Typed payloads for listing.* events (tr-content-platform listing module).

Three emitters, one file: the audit path (status changes), the permit-expiry beat,
and the portal sync writer. All ids are str (UUIDs stringified at emit); dates are
ISO str.
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


class ListingPortalSyncFailedV1(EventPayload):
    """listing.portal_sync_failed — one portal rejected or could not take a listing.

    Emitted once per failing (listing, portal) by the portal sync writer. Distinct
    from the audit events: the listing's own status may not change at all (another
    portal can still hold it live), so what matters here is which portal failed and
    why, not a status transition.

    Field set mirrors
    app/modules/listing/tasks/propertyfinder/sync_db.py:update_portal_publication_status.
    """

    entity_id: str
    entity_type: str
    listing_id: str
    listing_title: str | None = None
    portal_name: str
    error_message: str | None = None
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
