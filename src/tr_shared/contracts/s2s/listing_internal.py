"""S2S contract: tr-content-platform listing internal endpoints.

Provider: tr-content-platform (mounted at /api/v1/listing/internal/listings).
Callers: tr-lead-management, tr-crm-core (activity access-check).
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


class ListingInternalRef(BaseModel):
    """Lean caller-facing view of the by-reference response.

    Only the fields S2S callers actually read. The provider's full
    ``ListingInternalOut`` is a superset (guarded by a provider drift test);
    ``extra='ignore'`` lets the extra fields pass through harmlessly.
    """

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
    """Response of POST .../{listing_id}/leads:increment."""

    listing_id: UUID
    leads_count: int
    last_lead_at: datetime | None = None


class ListingActiveCountOut(BaseModel):
    """Data payload of GET .../active-count (inside SuccessResponse.data)."""

    count: int
