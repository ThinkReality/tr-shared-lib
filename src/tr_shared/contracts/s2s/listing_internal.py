"""S2S contract: tr-content-platform /api/v1/listing/internal/listings.
Callers: tr-lead-management, tr-crm-core.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

BASE_PATH = "/api/v1/listing/internal/listings"


def by_reference(reference_number: str) -> str:
    return f"{BASE_PATH}/by-reference/{reference_number}"


def active_count() -> str:
    return f"{BASE_PATH}/active-count"


def by_agent(agent_id: UUID | str) -> str:
    return f"{BASE_PATH}/by-agent/{agent_id}"


def leads_increment(listing_id: UUID | str) -> str:
    return f"{BASE_PATH}/{listing_id}/leads:increment"


def access_check(listing_id: UUID | str) -> str:
    return f"{BASE_PATH}/{listing_id}/access-check"


def agent_listing_counts_batch() -> str:
    return f"{BASE_PATH}/agents:batch-count"


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
    agent_ids: list[UUID]


class AgentListingCountRow(BaseModel):
    agent_id: UUID
    listings_count: int


class AgentListingCountsResponse(BaseModel):
    rows: list[AgentListingCountRow]
