"""HttpHeader is the cross-service header-name SSOT. Pin the identity members
so a rename can't silently desync gateway and downstream."""

from tr_shared.contracts.headers import HttpHeader


def test_site_id_header_name():
    assert HttpHeader.SITE_ID.value == "X-Site-Id"


def test_original_ip_header_name():
    """The gateway derives this from the real socket peer, strips any inbound
    copy, then re-sets it — so downstream may treat it as gateway-asserted.

    Pinned here because it is now read on both sides: the gateway writes it and
    tr-media-service keys its career-upload rate limit on it. It was a bare
    string literal in the gateway alone until A33, which is exactly the drift
    this enum exists to prevent.
    """
    assert HttpHeader.ORIGINAL_IP.value == "X-Original-IP"


def test_identity_header_names_are_pinned():
    assert HttpHeader.USER_ID.value == "X-User-ID"
    assert HttpHeader.USER_ROLE.value == "X-User-Role"
    assert HttpHeader.TENANT_ID.value == "X-Tenant-ID"
    assert HttpHeader.CORRELATION_ID.value == "X-Correlation-ID"
    assert HttpHeader.USER_EMAIL.value == "X-User-Email"
    assert HttpHeader.USER_PERMISSIONS.value == "X-User-Permissions"
