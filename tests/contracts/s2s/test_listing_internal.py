from uuid import uuid4

import pytest
from pydantic import ValidationError

from tr_shared.contracts.s2s import listing_internal as c


def test_agent_ids_capped_at_500():
    c.AgentListingCountsRequest(tenant_id=uuid4(), agent_ids=[uuid4() for _ in range(500)])
    with pytest.raises(ValidationError):
        c.AgentListingCountsRequest(tenant_id=uuid4(), agent_ids=[uuid4() for _ in range(501)])


def test_agent_listing_counts_batch_path():
    assert c.agent_listing_counts_batch() == "/api/v1/listing/internal/listings/agents:batch-count"


def test_agent_listing_count_row_shape():
    row = c.AgentListingCountRow(
        agent_id="11111111-1111-1111-1111-111111111111", listings_count=3
    )
    assert row.listings_count == 3
