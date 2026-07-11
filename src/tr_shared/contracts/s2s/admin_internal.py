"""S2S contract: tr-crm-core /api/v1/internal/admin config-warm endpoints.
Caller: tr-lead-management (D17/R10 — pulls active assignment rules + agent
groups to warm its in-memory config cache). Service-token authenticated.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

BASE_PATH = "/api/v1/internal/admin"


def assignment_rules() -> str:
    """Active assignment rules for a tenant (``?tenant_id=``)."""
    return f"{BASE_PATH}/assignment-rules"


def agent_groups() -> str:
    """Active agent groups + member UUIDs for a tenant (``?tenant_id=``)."""
    return f"{BASE_PATH}/agent-groups"


class AssignmentRuleRef(BaseModel):
    """Fields the routing engine reads. ``conditions``/``agents_team`` are UI-owned
    JSONB left opaque — validated on write in the admin rule-builder, not here."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    rule_name: str | None = None
    priority_number: int = 0
    is_active: bool = True
    conditions: list[dict] = []
    rule_condition_logic: str | None = None
    assignment_method: str | None = None
    agent_group_id: UUID | None = None
    agents_team: Any = None
    max_leads_per_day: int | None = None
    active_days: list[str] = []
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None


class AgentGroupMemberRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: UUID
    sort_order: int = 0


class AgentGroupRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    group_name: str
    is_active: bool = True
    version: int = 1
    members: list[AgentGroupMemberRef] = []
