"""get_gateway_tenant_id reads only what IdentityExtractionMiddleware verified.

The old get_public_tenant_id parsed a raw client header — any well-formed UUID
was accepted. These tests exist to keep that from coming back: a raw header with
no verified identity behind it must be rejected, not parsed.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from tr_shared.exceptions import AuthenticationError
from tr_shared.web import get_gateway_site_id, get_gateway_tenant_id


def _request(identity=None):
    """Minimal stand-in for starlette Request — the deps only touch .state."""
    state = SimpleNamespace()
    if identity is not None:
        state.identity = identity
    return SimpleNamespace(state=state, url=SimpleNamespace(path="/api/v1/public/x"))


async def test_returns_verified_tenant_id():
    tenant_id = uuid4()
    request = _request(SimpleNamespace(tenant_id=tenant_id, site_id=None))
    assert await get_gateway_tenant_id(request) == tenant_id


async def test_rejects_missing_identity_state():
    with pytest.raises(AuthenticationError):
        await get_gateway_tenant_id(_request())


async def test_rejects_identity_without_tenant():
    request = _request(SimpleNamespace(tenant_id=None, site_id=None))
    with pytest.raises(AuthenticationError):
        await get_gateway_tenant_id(request)


async def test_site_id_returned_when_present():
    site_id = uuid4()
    request = _request(SimpleNamespace(tenant_id=uuid4(), site_id=site_id))
    assert await get_gateway_site_id(request) == site_id


async def test_site_id_is_none_when_absent():
    request = _request(SimpleNamespace(tenant_id=uuid4(), site_id=None))
    assert await get_gateway_site_id(request) is None


async def test_site_id_is_none_without_identity_state():
    assert await get_gateway_site_id(_request()) is None


def test_public_tenant_dependency_is_gone():
    """The header-trusting dependency must not be importable — an accidental
    re-add would silently reopen the bypass."""
    import tr_shared.web as web

    assert not hasattr(web, "get_public_tenant_id")
    assert "get_public_tenant_id" not in web.__all__
