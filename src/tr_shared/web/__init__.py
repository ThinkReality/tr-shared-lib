"""Reusable FastAPI dependencies and web-layer helpers."""

from tr_shared.web.dependencies import get_gateway_site_id, get_gateway_tenant_id

__all__ = ["get_gateway_site_id", "get_gateway_tenant_id"]
