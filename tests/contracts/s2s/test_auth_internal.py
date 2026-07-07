from uuid import uuid4

from tr_shared.contracts.s2s import auth_internal


def test_internal_call_headers_builds_both_calling_headers():
    tid = uuid4()
    headers = auth_internal.internal_call_headers("content-platform", tid)

    assert headers == {
        "X-Calling-Service": "content-platform",
        "X-Calling-Tenant-ID": str(tid),
    }


def test_internal_call_headers_accepts_str_tenant():
    headers = auth_internal.internal_call_headers("people-finance", "abc-123")
    assert headers["X-Calling-Tenant-ID"] == "abc-123"


def test_portal_agents_resolve_or_create_path():
    assert (
        auth_internal.portal_agents_resolve_or_create()
        == "/api/v1/internal/portal-agents/resolve-or-create"
    )


def test_upsert_ref_allows_null_crm_user_id():
    ref = auth_internal.PortalAgentResolveOrCreateRef.model_validate(
        {"resolved": {"999": {"crm_user_id": None, "name": "Ghost"}}}
    )
    assert ref.resolved["999"].crm_user_id is None
    assert ref.resolved["999"].name == "Ghost"


def test_upsert_ref_parses_matched_uuid():
    uid = uuid4()
    ref = auth_internal.PortalAgentResolveOrCreateRef.model_validate(
        {"resolved": {"111": {"crm_user_id": str(uid), "name": "Alice"}}}
    )
    assert ref.resolved["111"].crm_user_id == uid
