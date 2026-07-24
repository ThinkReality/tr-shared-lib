"""S2S contract: tr-content-platform ``/api/v1/listing/internal``.
Callers: tr-lead-management, tr-crm-core.

Two resources share the provider root:

- ``/listings`` — listing reads and the lead-count write.
- ``/portal-publications`` — per-portal sync state
  (``listing_schema.listing_portal_publications``).

``recent_sync_activity`` is fully specified here — path, query, and response —
so callers never hand-build any part of it.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

INTERNAL_ROOT = "/api/v1/listing/internal"
LISTINGS_BASE_PATH = f"{INTERNAL_ROOT}/listings"
PORTAL_PUBLICATIONS_BASE_PATH = f"{INTERNAL_ROOT}/portal-publications"


def by_reference(reference_number: str) -> str:
    return f"{LISTINGS_BASE_PATH}/by-reference/{reference_number}"


def active_count() -> str:
    return f"{LISTINGS_BASE_PATH}/active-count"


def by_agent(agent_id: UUID | str) -> str:
    return f"{LISTINGS_BASE_PATH}/by-agent/{agent_id}"


def leads_increment(listing_id: UUID | str) -> str:
    return f"{LISTINGS_BASE_PATH}/{listing_id}/leads:increment"


def access_check(listing_id: UUID | str) -> str:
    return f"{LISTINGS_BASE_PATH}/{listing_id}/access-check"


def agent_listing_counts_batch() -> str:
    return f"{LISTINGS_BASE_PATH}/agents:batch-count"


def recent_sync_activity() -> str:
    return f"{PORTAL_PUBLICATIONS_BASE_PATH}/recent-sync-activity"


class PortalSyncStatus(StrEnum):
    """Sync state of one listing↔portal publication row.

    Owned by tr-content-platform: it is the CHECK-constrained vocabulary of
    ``listing_schema.listing_portal_publications.portal_sync_status``
    (``ck_listing_portal_publications_portal_sync_status``). Declared here
    because tr-crm-core filters and renders these values over the
    ``recent_sync_activity`` contract below, and previously kept its own
    disagreeing copy (``success``/``failed``/``pending``) — which silently
    matched zero rows on filter and never matched a description key.

    Adding or removing a member requires a forward migration in
    tr-content-platform that regenerates the CHECK constraint.
    """

    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"
    DISABLED = "disabled"
    ACTION_REQUIRED = "action_required"


class ListingInternalRef(BaseModel):
    """Lean S2S view; extra='ignore' lets provider add fields without breaking callers.
    Provider superset drift is guarded by a contract test."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    reference_number: str | None = None
    listing_status: str
    title_en: str | None = None
    tenant_id: UUID
    leads_count: int = 0
    last_lead_at: datetime | None = None
    # JSONB dicts in the DB: {"id": ..., "name": ...}
    listing_owner: dict | None = None
    listing_agent: dict | None = None


class ListingLeadCountOut(BaseModel):
    listing_id: UUID
    leads_count: int
    last_lead_at: datetime | None = None


class ListingActiveCountOut(BaseModel):
    count: int


class AgentListingCountsRequest(BaseModel):
    tenant_id: UUID
    agent_ids: list[UUID] = Field(..., max_length=500)


class AgentListingCountRow(BaseModel):
    agent_id: UUID
    listings_count: int


class AgentListingCountsResponse(BaseModel):
    rows: list[AgentListingCountRow]


class PortalSyncActivityQuery(BaseModel):
    """Query vocabulary for ``recent_sync_activity()``.

    Both sides declare these here and nowhere else: the provider takes it as
    ``Annotated[PortalSyncActivityQuery, Query()]``, the consumer sends
    ``model_dump(mode="json", exclude_none=True)``. A key that drifts on one
    side is then a 422, not an HTTP 200 with the filter silently ignored.

    ``extra="forbid"`` is deliberate and is the opposite of
    ``PortalSyncActivityRow``'s ``extra="ignore"``. A response may legitimately
    grow fields an older caller does not know; a request may not — an
    unrecognised query key means the caller believes it is filtering when it is
    not, so it must fail loudly.

    Defaults belong here for the same reason the bounds do: they are the
    contract. Note this is the reverse of ``PortalSyncActivityRow``, whose
    nullable fields carry no default — there, absent means provider drift; here,
    absent means "caller did not ask", which has a defined answer.
    """

    model_config = ConfigDict(extra="forbid")

    portal_name: str | None = None
    sync_status: PortalSyncStatus | None = None
    limit: int = Field(20, ge=1, le=100)
    hours_back: int = Field(24, ge=1, le=168)


class PortalSyncActivityRow(BaseModel):
    """One publication row as the monitoring caller reads it.

    ``portal_name`` stays ``str`` deliberately. The canonical typed vocabulary is
    ``tr_shared.integrations.PortalSlug``, but ``tr_shared.integrations``'s package
    ``__init__`` imports ``config_client`` → ``httpx``, and ``contracts/`` is a
    declarations-only package with no runtime dependencies beyond pydantic.
    Importing it here would couple every contract consumer to an optional extra.
    The producer's DB CHECK already constrains this column to the four listing
    portal slugs.

    ``portal_sync_error``, ``last_synced_at`` and ``portal_listing_status`` carry
    no default: they are required-but-nullable, so an explicit ``null`` still
    validates but a missing key raises — a renamed field is a type error, not a
    silent ``None``.
    """

    model_config = ConfigDict(extra="ignore")

    id: UUID
    portal_name: str
    portal_sync_status: PortalSyncStatus
    portal_sync_error: str | None
    last_synced_at: datetime | None
    portal_listing_status: str | None
    enabled: bool


class PortalSyncActivityPage(BaseModel):
    activities: list[PortalSyncActivityRow]
    total_count: int
