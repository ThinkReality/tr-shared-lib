"""D17 — admin config-change events (rule update/delete + agent-group CRUD).

These drive lead-management's config-cache invalidation (R10).
"""

import pytest
from pydantic import ValidationError

from tr_shared.events.event_types import AdminEvents
from tr_shared.events import payloads
from tr_shared.events.payloads import (
    AdminAgentGroupCreatedV1,
    AdminAgentGroupDeletedV1,
    AdminAgentGroupUpdatedV1,
    AdminAssignmentRuleDeletedV1,
    AdminAssignmentRuleUpdatedV1,
)


def test_agent_group_event_type_values():
    assert AdminEvents.AGENT_GROUP_CREATED == "admin.agent_group.created"
    assert AdminEvents.AGENT_GROUP_UPDATED == "admin.agent_group.updated"
    assert AdminEvents.AGENT_GROUP_DELETED == "admin.agent_group.deleted"


def test_assignment_rule_mutation_event_values():
    assert AdminEvents.ASSIGNMENT_RULE_UPDATED == "admin.assignment_rule.updated"
    assert AdminEvents.ASSIGNMENT_RULE_DELETED == "admin.assignment_rule.deleted"


def test_payloads_validate_minimal_shape():
    assert AdminAgentGroupCreatedV1(group_id="g", group_name="G").group_id == "g"
    assert AdminAgentGroupUpdatedV1(group_id="g", group_name="G").group_name == "G"
    assert AdminAgentGroupDeletedV1(group_id="g").group_id == "g"
    assert AdminAssignmentRuleUpdatedV1(rule_id="r", rule_name="R").rule_id == "r"
    assert AdminAssignmentRuleDeletedV1(rule_id="r").rule_id == "r"


def test_payloads_forbid_extra_keys():
    with pytest.raises(ValidationError):
        AdminAgentGroupDeletedV1(group_id="g", surprise="x")


def test_payloads_exported_from_package():
    for name in (
        "AdminAgentGroupCreatedV1",
        "AdminAgentGroupUpdatedV1",
        "AdminAgentGroupDeletedV1",
        "AdminAssignmentRuleUpdatedV1",
        "AdminAssignmentRuleDeletedV1",
    ):
        assert name in payloads.__all__
        assert hasattr(payloads, name)
