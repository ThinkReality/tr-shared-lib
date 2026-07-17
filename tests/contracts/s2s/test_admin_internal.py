from uuid import uuid4

import pytest
from pydantic import ValidationError

from tr_shared.contracts.s2s import admin_internal
from tr_shared.contracts.s2s.admin_internal import (
    CONDITION_OPERATORS,
    ConditionComparison,
    ConditionName,
    RuleCondition,
    RuleConditionLogic,
)


def test_assignment_rules_path():
    assert admin_internal.assignment_rules() == "/api/v1/internal/admin/assignment-rules"


def test_agent_groups_path():
    assert admin_internal.agent_groups() == "/api/v1/internal/admin/agent-groups"


def _valid_rule_payload(**overrides) -> dict:
    payload = {
        "id": str(uuid4()),
        "rule_name": "R1",
        "priority_number": 3,
        "is_active": True,
        "assignment_method": "round_robin",
        "conditions": [
            {
                "condition_name": "Lead Source",
                "condition_comparison": "In",
                "condition_value": "bayut,propertyfinder",
            }
        ],
        "rule_condition_logic": "ALL",
        "active_days": ["Mon", "Tue"],
    }
    payload.update(overrides)
    return payload


def test_condition_enum_values():
    assert ConditionName.BUDGET == "Budget"
    assert ConditionComparison.GREATER_THAN == "Greater Than"
    assert RuleConditionLogic.ALL == "ALL"


def test_rule_ref_parses_typed_conditions_and_ignores_extra():
    gid = uuid4()
    ref = admin_internal.AssignmentRuleRef.model_validate(
        _valid_rule_payload(agent_group_id=str(gid), created_at="2026-07-11T00:00:00")
    )
    assert ref.agent_group_id == gid
    assert ref.rule_condition_logic is RuleConditionLogic.ALL
    assert ref.conditions[0].condition_name is ConditionName.LEAD_SOURCE
    assert ref.conditions[0].condition_comparison is ConditionComparison.IN
    assert ref.max_leads_per_day is None
    assert ref.active_days == ["Mon", "Tue"]


def test_rule_ref_null_agent_group_and_empty_conditions():
    ref = admin_internal.AssignmentRuleRef.model_validate(
        _valid_rule_payload(agent_group_id=None, conditions=[])
    )
    assert ref.agent_group_id is None
    assert ref.conditions == []


def test_rule_ref_requires_is_active():
    payload = _valid_rule_payload()
    del payload["is_active"]
    with pytest.raises(ValidationError):
        admin_internal.AssignmentRuleRef.model_validate(payload)


def test_rule_ref_requires_priority_number():
    payload = _valid_rule_payload()
    del payload["priority_number"]
    with pytest.raises(ValidationError):
        admin_internal.AssignmentRuleRef.model_validate(payload)


def test_rule_condition_rejects_out_of_vocab_name():
    with pytest.raises(ValidationError):
        RuleCondition.model_validate(
            {
                "condition_name": "Zodiac Sign",
                "condition_comparison": "Equals",
                "condition_value": "Leo",
            }
        )


def test_rule_condition_rejects_out_of_vocab_operator():
    with pytest.raises(ValidationError):
        RuleCondition.model_validate(
            {
                "condition_name": "Lead Score",
                "condition_comparison": "Roughly Equals",
                "condition_value": "80",
            }
        )


def test_rule_condition_logic_rejects_lowercase():
    payload = _valid_rule_payload(rule_condition_logic="all")
    with pytest.raises(ValidationError):
        admin_internal.AssignmentRuleRef.model_validate(payload)


def test_condition_operators_cover_every_field():
    assert set(CONDITION_OPERATORS) == set(ConditionName)


def test_condition_operators_numeric_fields_allow_ordering():
    assert ConditionComparison.GREATER_THAN in CONDITION_OPERATORS[ConditionName.LEAD_SCORE]
    assert ConditionComparison.LESS_THAN in CONDITION_OPERATORS[ConditionName.BUDGET]


def test_condition_operators_scalar_fields_reject_ordering():
    for field in (
        ConditionName.LEAD_SOURCE,
        ConditionName.LANGUAGE,
        ConditionName.PROPERTY_TYPE,
        ConditionName.LOCATION,
        ConditionName.URGENCY,
    ):
        assert ConditionComparison.GREATER_THAN not in CONDITION_OPERATORS[field]
        assert ConditionComparison.LESS_THAN not in CONDITION_OPERATORS[field]
        assert ConditionComparison.EQUALS in CONDITION_OPERATORS[field]


def test_rule_ref_sla_fields_default_when_absent():
    ref = admin_internal.AssignmentRuleRef.model_validate(_valid_rule_payload())
    assert ref.auto_reassign_after_minutes is None
    assert ref.escalate_to_manager_if_no_response is False
    assert ref.notifications is None


def test_rule_ref_parses_sla_fields():
    ref = admin_internal.AssignmentRuleRef.model_validate(
        _valid_rule_payload(
            auto_reassign_after_minutes=30,
            escalate_to_manager_if_no_response=True,
            notifications={
                "notify_team_leader": True,
                "notification_channels": ["in_app", "email"],
            },
        )
    )
    assert ref.auto_reassign_after_minutes == 30
    assert ref.escalate_to_manager_if_no_response is True
    assert ref.notifications is not None
    assert ref.notifications.notify_assigned_agent is True
    assert ref.notifications.notify_team_leader is True
    assert ref.notifications.notification_channels == ["in_app", "email"]


def test_rule_notifications_defaults():
    n = admin_internal.RuleNotifications()
    assert n.notify_assigned_agent is True
    assert n.notify_team_leader is False
    assert n.notification_channels == ["in_app"]


def test_group_ref_parses_members_sorted_shape():
    gid, a1, a2 = uuid4(), uuid4(), uuid4()
    ref = admin_internal.AgentGroupRef.model_validate(
        {
            "id": str(gid),
            "group_name": "Sales",
            "members": [
                {"agent_id": str(a1), "sort_order": 0},
                {"agent_id": str(a2), "sort_order": 1},
            ],
        }
    )
    assert ref.group_name == "Sales"
    assert [m.agent_id for m in ref.members] == [a1, a2]
