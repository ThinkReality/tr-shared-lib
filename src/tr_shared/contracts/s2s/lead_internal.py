"""S2S contract: tr-lead-management /api/v1/internal/leads.
Callers: tr-crm-core. Access-check models: tr_shared.contracts.s2s.access_check.
"""

from uuid import UUID

from pydantic import BaseModel, Field

BASE_PATH = "/api/v1/internal/leads"


def access_check(lead_id: UUID | str) -> str:
    return f"{BASE_PATH}/{lead_id}/access-check"


def agent_lead_counts_batch() -> str:
    return f"{BASE_PATH}/agents/kpi-batch"


def by_agent_counts() -> str:
    """Per-agent active + total lead counts (optional ?agent_id= narrows to one)."""
    return f"{BASE_PATH}/by-agent"


def by_agent_leads(agent_id: UUID | str) -> str:
    """Paginated leads assigned to one agent (?status=active|all)."""
    return f"{BASE_PATH}/by-agent/{agent_id}"


class AgentLeadCountsRequest(BaseModel):
    tenant_id: UUID
    agent_ids: list[UUID] = Field(..., max_length=500)


class AgentLeadCountPair(BaseModel):
    """One row of the by-agent counts endpoint: active AND total in a single call
    so a dashboard's active/total toggle needs no second request."""

    agent_id: UUID
    active_count: int
    total_count: int


class AgentLeadCountRow(BaseModel):
    agent_id: UUID
    leads_count: int
    # no lead-outcome model yet
    converted_leads_count: int = 0
    # no deal model yet
    deals_count: int = 0


class AgentLeadCountsResponse(BaseModel):
    rows: list[AgentLeadCountRow]
