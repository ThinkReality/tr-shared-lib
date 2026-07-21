"""S2S contract: tr-crm-core /api/v1/internal/admin config-warm endpoints.
Caller: tr-lead-management (D17/R10 — pulls active assignment rules + agent
groups to warm its in-memory config cache). Service-token authenticated.

The routing-rule condition vocabulary (D24) lives HERE as the single source of
truth: the admin rule-builder (producer), the lead-mgmt routing engine
(consumer), and — via OpenAPI — the frontend all derive from these enums, so a
value can never drift across the four surfaces that used to hand-sync it.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

BASE_PATH = "/api/v1/internal/admin"


def assignment_rules() -> str:
    """Active assignment rules for a tenant (``?tenant_id=``)."""
    return f"{BASE_PATH}/assignment-rules"


def agent_groups() -> str:
    """Active agent groups + member UUIDs for a tenant (``?tenant_id=``)."""
    return f"{BASE_PATH}/agent-groups"


class ConditionName(StrEnum):
    """The 7 fixed fields an assignment-rule condition can test (D24)."""

    LEAD_SCORE = "Lead Score"
    LEAD_SOURCE = "Lead Source"
    LANGUAGE = "Language"
    PROPERTY_TYPE = "Property Type"
    BUDGET = "Budget"
    LOCATION = "Location"
    URGENCY = "Urgency"


class ConditionComparison(StrEnum):
    EQUALS = "Equals"
    NOT_EQUALS = "Not Equals"
    GREATER_THAN = "Greater Than"
    LESS_THAN = "Less Than"
    IN = "In"


class RuleConditionLogic(StrEnum):
    """How a rule combines its conditions."""

    ALL = "ALL"
    ANY = "ANY"


class AssignmentMethod(StrEnum):
    """Canonical lead-assignment methods (v1 scope) — SSOT for the admin
    rule-builder (producer), the lead-mgmt routing engine (consumer), and the
    frontend via OpenAPI. Attribute-routing (``by_*``) was removed: never
    implemented, ran as silent round-robin."""

    ROUND_ROBIN = "round_robin"
    SPECIFIC_AGENT = "specific_agent"
    SPECIFIC_AGENT_TEAM = "specific_agent_team"
    SPECIFIC_USER = "specific_user"
    TEAM_BASED = "team_based"
    LEAD_LOAD_QUEUE = "lead_load_queue"


# Which operators the routing engine actually supports per field (mirrors
# condition_evaluator: numeric fields order, everything else is scalar/list
# membership only). SSOT the admin rule-builder validates writes against, so it
# can never save an operator the engine will silently drop.
CONDITION_OPERATORS: Mapping[ConditionName, frozenset[ConditionComparison]] = {
    ConditionName.LEAD_SCORE: frozenset(ConditionComparison),
    ConditionName.BUDGET: frozenset(ConditionComparison),
    ConditionName.LEAD_SOURCE: frozenset(
        {ConditionComparison.EQUALS, ConditionComparison.NOT_EQUALS, ConditionComparison.IN}
    ),
    ConditionName.LANGUAGE: frozenset(
        {ConditionComparison.EQUALS, ConditionComparison.NOT_EQUALS, ConditionComparison.IN}
    ),
    ConditionName.PROPERTY_TYPE: frozenset(
        {ConditionComparison.EQUALS, ConditionComparison.NOT_EQUALS, ConditionComparison.IN}
    ),
    ConditionName.LOCATION: frozenset(
        {ConditionComparison.EQUALS, ConditionComparison.NOT_EQUALS, ConditionComparison.IN}
    ),
    ConditionName.URGENCY: frozenset(
        {ConditionComparison.EQUALS, ConditionComparison.NOT_EQUALS, ConditionComparison.IN}
    ),
}


class RuleCondition(BaseModel):
    """One condition of an assignment rule. Wire keys match producer and consumer
    verbatim; enum-typing makes an out-of-vocab value a parse error, not a silent
    no-match."""

    model_config = ConfigDict(extra="ignore")

    condition_name: ConditionName
    condition_comparison: ConditionComparison
    condition_value: str | int | float


class RuleNotifications(BaseModel):
    """Per-rule notification settings the lead SLA layer honors when a lead is
    assigned/reassigned. ``notification_channels`` are wire strings (in_app/email/
    sms/push/whatsapp) — kept as ``str`` so the S2S contract stays decoupled from
    the notification service's Channel enum; the consumer passes them through."""

    model_config = ConfigDict(extra="ignore")

    notify_assigned_agent: bool = True
    notify_team_leader: bool = False
    notification_channels: list[str] = Field(default_factory=lambda: ["in_app"])


class AssignmentRuleRef(BaseModel):
    """Fields the routing engine reads. ``agents_team`` is UI-owned JSONB left
    opaque (individually-named agent targets) — validated on write in the admin
    rule-builder, not here."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    rule_name: str | None = None
    priority_number: int
    is_active: bool
    conditions: list[RuleCondition] = []
    rule_condition_logic: RuleConditionLogic | None = None
    assignment_method: AssignmentMethod | None = None
    agent_group_id: UUID | None = None
    agents_team: Any = None
    max_leads_per_day: int | None = None
    active_days: list[str] = []
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    # Lead SLA (no-response reaction) — consumed by lead-mgmt's reassign/escalate sweep.
    auto_reassign_after_minutes: int | None = None
    escalate_to_manager_if_no_response: bool = False
    notifications: RuleNotifications | None = None


class AgentGroupMemberRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: UUID
    sort_order: int = 0


class AgentGroupRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    group_name: str
    is_active: bool = True
    members: list[AgentGroupMemberRef] = []
