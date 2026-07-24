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


def test_internal_root_and_resource_prefixes():
    assert c.INTERNAL_ROOT == "/api/v1/listing/internal"
    assert c.LISTINGS_BASE_PATH == "/api/v1/listing/internal/listings"
    assert c.PORTAL_PUBLICATIONS_BASE_PATH == "/api/v1/listing/internal/portal-publications"


def test_existing_listing_paths_unchanged_after_prefix_split():
    assert c.by_reference("REF-1") == "/api/v1/listing/internal/listings/by-reference/REF-1"
    assert c.active_count() == "/api/v1/listing/internal/listings/active-count"
    assert c.by_agent("abc") == "/api/v1/listing/internal/listings/by-agent/abc"
    assert c.leads_increment("xyz") == "/api/v1/listing/internal/listings/xyz/leads:increment"
    assert c.access_check("xyz") == "/api/v1/listing/internal/listings/xyz/access-check"


def test_recent_sync_activity_path():
    assert (
        c.recent_sync_activity()
        == "/api/v1/listing/internal/portal-publications/recent-sync-activity"
    )


def test_portal_sync_status_values_match_the_db_check_constraint():
    """These six are CHECK-constrained on
    listing_schema.listing_portal_publications.portal_sync_status. Changing this
    set without a forward migration in tr-content-platform breaks writes."""
    assert {s.value for s in c.PortalSyncStatus} == {
        "pending",
        "syncing",
        "synced",
        "error",
        "disabled",
        "action_required",
    }


def test_activity_row_coerces_sync_status_to_enum():
    row = c.PortalSyncActivityRow.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "portal_name": "propertyfinder",
            "portal_sync_status": "action_required",
            "portal_sync_error": None,
            "last_synced_at": None,
            "portal_listing_status": None,
            "enabled": True,
        }
    )
    assert row.portal_sync_status is c.PortalSyncStatus.ACTION_REQUIRED
    assert row.portal_sync_error is None
    assert row.last_synced_at is None
    assert row.portal_listing_status is None


def test_activity_row_rejects_out_of_vocab_sync_status():
    with pytest.raises(ValidationError):
        c.PortalSyncActivityRow.model_validate(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "portal_name": "propertyfinder",
                "portal_sync_status": "success",
                "enabled": True,
            }
        )


def test_activity_row_ignores_extra_provider_fields():
    row = c.PortalSyncActivityRow.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "portal_name": "bayut",
            "portal_sync_status": "synced",
            "portal_sync_error": None,
            "last_synced_at": "2026-07-24T10:00:00Z",
            "portal_listing_status": "live",
            "enabled": True,
            "pf_quality_score_value": "88.50",
        }
    )
    assert row.portal_sync_status is c.PortalSyncStatus.SYNCED


def test_activity_page_shape():
    page = c.PortalSyncActivityPage.model_validate({"activities": [], "total_count": 0})
    assert page.activities == []
    assert page.total_count == 0


def test_activity_row_rejects_missing_nullable_field():
    """Omitting a nullable-but-required field must raise — this is what turns a
    provider-side column rename into a hard error instead of a silently blank column."""
    with pytest.raises(ValidationError):
        c.PortalSyncActivityRow.model_validate(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "portal_name": "propertyfinder",
                "portal_sync_status": "synced",
                "last_synced_at": None,
                "portal_listing_status": None,
                "enabled": True,
            }
        )


def test_activity_query_defaults():
    q = c.PortalSyncActivityQuery()
    assert q.limit == 20
    assert q.hours_back == 24
    assert q.portal_name is None
    assert q.sync_status is None


def test_activity_query_bounds():
    for limit in (0, 101):
        with pytest.raises(ValidationError):
            c.PortalSyncActivityQuery(limit=limit)
    for hours_back in (0, 169):
        with pytest.raises(ValidationError):
            c.PortalSyncActivityQuery(hours_back=hours_back)
    assert c.PortalSyncActivityQuery(limit=100, hours_back=168).limit == 100


def test_activity_query_sync_status_uses_the_shared_vocabulary():
    """The consumer previously validated this against its own
    success/failed/pending enum, which matched zero rows. Those values must now
    be rejected at the contract boundary."""
    q = c.PortalSyncActivityQuery(sync_status="action_required")
    assert q.sync_status is c.PortalSyncStatus.ACTION_REQUIRED
    with pytest.raises(ValidationError):
        c.PortalSyncActivityQuery(sync_status="success")


def test_activity_query_forbids_unknown_keys():
    """extra='forbid' is what turns a drifted param name into a 422 instead of
    an HTTP 200 with the filter silently ignored."""
    with pytest.raises(ValidationError):
        c.PortalSyncActivityQuery.model_validate({"status_filter": "synced"})


def test_activity_query_serializes_to_wire_params():
    q = c.PortalSyncActivityQuery(portal_name="bayut", sync_status=c.PortalSyncStatus.ERROR)
    assert q.model_dump(mode="json", exclude_none=True) == {
        "portal_name": "bayut",
        "sync_status": "error",
        "limit": 20,
        "hours_back": 24,
    }
