from uuid import uuid4

import pytest
from pydantic import ValidationError

from tr_shared.contracts.s2s import lead_internal as c


def test_agent_ids_capped_at_500():
    c.AgentLeadCountsRequest(tenant_id=uuid4(), agent_ids=[uuid4() for _ in range(500)])
    with pytest.raises(ValidationError):
        c.AgentLeadCountsRequest(tenant_id=uuid4(), agent_ids=[uuid4() for _ in range(501)])


def test_agent_lead_counts_batch_path():
    assert c.agent_lead_counts_batch() == "/api/v1/internal/leads/agents/kpi-batch"


def test_row_defaults_zero_for_unmodeled_metrics():
    row = c.AgentLeadCountRow(
        agent_id="11111111-1111-1111-1111-111111111111", leads_count=5
    )
    assert row.converted_leads_count == 0 and row.deals_count == 0
