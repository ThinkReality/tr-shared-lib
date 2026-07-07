"""S2S contract: tr-lead-management /api/v1/internal/leads.
Callers: tr-crm-core. Access-check models: tr_shared.contracts.s2s.access_check.
"""

from uuid import UUID

from pydantic import BaseModel

BASE_PATH = "/api/v1/internal/leads"


def access_check(lead_id: UUID | str) -> str:
    return f"{BASE_PATH}/{lead_id}/access-check"


def agent_lead_counts_batch() -> str:
    return f"{BASE_PATH}/agents/kpi-batch"


class AgentLeadCountsRequest(BaseModel):
    tenant_id: UUID
    agent_ids: list[UUID]


class AgentLeadCountRow(BaseModel):
    agent_id: UUID
    leads_count: int
    # no lead-outcome model yet
    converted_leads_count: int = 0
    # no deal model yet
    deals_count: int = 0


class AgentLeadCountsResponse(BaseModel):
    rows: list[AgentLeadCountRow]
