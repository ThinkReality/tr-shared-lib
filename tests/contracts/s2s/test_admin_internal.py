from uuid import uuid4

from tr_shared.contracts.s2s import admin_internal


def test_assignment_rules_path():
    assert admin_internal.assignment_rules() == "/api/v1/internal/admin/assignment-rules"


def test_agent_groups_path():
    assert admin_internal.agent_groups() == "/api/v1/internal/admin/agent-groups"


def test_rule_ref_ignores_extra_and_defaults():
    rid, gid = uuid4(), uuid4()
    ref = admin_internal.AssignmentRuleRef.model_validate(
        {
            "id": str(rid),
            "rule_name": "R1",
            "priority_number": 3,
            "assignment_method": "round_robin",
            "agent_group_id": str(gid),
            "conditions": [{"field": "source", "operator": "eq", "value": "bayut"}],
            "rule_condition_logic": "all",
            "active_days": ["mon", "tue"],
            "created_at": "2026-07-11T00:00:00",
        }
    )
    assert ref.id == rid
    assert ref.agent_group_id == gid
    assert ref.rule_condition_logic == "all"
    assert ref.max_leads_per_day is None
    assert ref.active_days == ["mon", "tue"]


def test_rule_ref_null_agent_group():
    ref = admin_internal.AssignmentRuleRef.model_validate({"id": str(uuid4())})
    assert ref.agent_group_id is None
    assert ref.conditions == []


def test_group_ref_parses_members_sorted_shape():
    gid, a1, a2 = uuid4(), uuid4(), uuid4()
    ref = admin_internal.AgentGroupRef.model_validate(
        {
            "id": str(gid),
            "group_name": "Sales",
            "version": 2,
            "members": [
                {"agent_id": str(a1), "sort_order": 0},
                {"agent_id": str(a2), "sort_order": 1},
            ],
        }
    )
    assert ref.group_name == "Sales"
    assert [m.agent_id for m in ref.members] == [a1, a2]
