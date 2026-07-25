"""HttpHeader is the cross-service header-name SSOT. Pin the identity members
so a rename can't silently desync gateway and downstream."""

from tr_shared.contracts.headers import HttpHeader


def test_site_id_header_name():
    assert HttpHeader.SITE_ID.value == "X-Site-Id"


def test_identity_header_names_are_pinned():
    assert HttpHeader.USER_ID.value == "X-User-ID"
    assert HttpHeader.USER_ROLE.value == "X-User-Role"
    assert HttpHeader.TENANT_ID.value == "X-Tenant-ID"
    assert HttpHeader.CORRELATION_ID.value == "X-Correlation-ID"
    assert HttpHeader.USER_EMAIL.value == "X-User-Email"
    assert HttpHeader.USER_PERMISSIONS.value == "X-User-Permissions"
