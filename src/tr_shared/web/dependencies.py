"""Identity dependencies for gateway-fronted routes.

The gateway is the sole authority for tenant identity. It derives tenant from a
validated JWT (authenticated routes) or from a resolved site key (public routes),
signs it into ``X-Tenant-ID``, and downstream ``GatewayHMACMiddleware`` verifies
that signature before ``IdentityExtractionMiddleware`` parses it onto
``request.state.identity``.

These dependencies read *only* that parsed state. They never touch a raw header —
that is the whole point. The dependency they replace, ``get_public_tenant_id``,
parsed ``X-Tenant-ID`` straight off the wire, so any well-formed UUID was accepted
on every public route.
"""

from uuid import UUID

from fastapi import Request

from tr_shared.exceptions import AuthenticationError
from tr_shared.logging import get_logger

logger = get_logger(__name__)


async def get_gateway_tenant_id(request: Request) -> UUID:
    """Tenant for a gateway-fronted route, from HMAC-verified identity.

    Raises AuthenticationError when no verified tenant is present — which means
    the request did not come through the gateway, or the gateway had no identity
    to sign (no JWT and no valid site key).
    """
    identity = getattr(request.state, "identity", None)
    tenant_id: UUID | None = (
        getattr(identity, "tenant_id", None) if identity is not None else None
    )
    if tenant_id is None:
        logger.warning("gateway_tenant_missing", path=request.url.path)
        raise AuthenticationError("Request carries no verified tenant identity")
    return tenant_id


async def get_gateway_site_id(request: Request) -> UUID | None:
    """Originating site for a site-key route, or None on an authenticated route.

    Optional by design: the same handler serves both a public site-key call and
    an authenticated CRM call, and only the former has a site.
    """
    identity = getattr(request.state, "identity", None)
    site_id: UUID | None = (
        getattr(identity, "site_id", None) if identity is not None else None
    )
    return site_id
