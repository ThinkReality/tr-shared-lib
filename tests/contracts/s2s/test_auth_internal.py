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
