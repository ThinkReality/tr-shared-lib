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
