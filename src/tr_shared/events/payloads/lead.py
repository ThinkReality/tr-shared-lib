"""Typed payloads for lead.* events (tr-lead-management).

``lead.created`` is emitted by a single durable emitter. PII (phone/email) is
ALWAYS hashed before the bus — ``hashed_phone``/``hashed_email`` are the only
PII-derived fields and carry hashed values, never raw.

Field sets mirror app/events/publisher.py:build_lead_lifecycle_payload. All ids
are str (UUIDs stringified at emit).
"""

from typing import Any

from tr_shared.events.payloads._base import EventPayload


class LeadEventV1(EventPayload):
    """Common fields present in every lead event data dict."""

    entity_type: str
    entity_id: str
    lead_id: str
    lead_name: str | None = None


class LeadCreatedV1(LeadEventV1):
    """lead.created — unified superset of the minimal + rich emitter shapes."""

    hashed_phone: str | None = None
    hashed_email: str | None = None
    source: str | None = None
    listing_reference: str | None = None
    tenant_id: str | None = None
    lead_type: str | None = None
    stage: str | None = None
    status: str | None = None
    lead_score: int | None = None
    lead_quality_tier: str | None = None
    assigned_to: str | None = None
    recipient_id: str | None = None
    created_by: str | None = None
    actor_id: str | None = None


class LeadAssignedV1(LeadEventV1):
    """lead.assigned — assignment + reassignment audit."""

    assigned_to: str
    assigned_by: str | None = None
    hashed_phone: str | None = None
    listing_reference: str | None = None
    assignment_reason: str | None = None


class LeadStatusChangedV1(LeadEventV1):
    """lead.status_changed."""

    old_status: str | None = None
    new_status: str
    assigned_to: str | None = None
    changes: dict[str, Any] | None = None


class LeadQualifiedV1(LeadEventV1):
    """lead.qualified."""

    qualification_score: int | None = None
    assigned_to: str | None = None


class LeadFollowupDueV1(LeadEventV1):
    """lead.followup_due."""

    followup_date: str | None = None
    assigned_to: str | None = None
