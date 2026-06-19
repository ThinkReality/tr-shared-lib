"""FastAPI dependencies usable by any service.

``get_public_tenant_id`` — extract and validate the ``X-Tenant-ID`` header for
public (unauthenticated) endpoints. SSOT replacing per-module copies in
content-platform (cms + listing) and other services.
"""

from uuid import UUID

from fastapi import Header

from tr_shared.exceptions import ValidationError
from tr_shared.logging import get_logger

logger = get_logger(__name__)


async def get_public_tenant_id(
    x_tenant_id: str = Header(
        ...,
        alias="X-Tenant-ID",
        description="Tenant UUID — required on all public endpoints",
    ),
) -> UUID:
    """Extract and validate the tenant UUID from the ``X-Tenant-ID`` header.

    No JWT required — UUID format validation only. Raises ``ValidationError``
    (HTTP 400) on a missing or malformed value. Public endpoints relying on this
    are expected to be rate-limited separately.
    """
    try:
        return UUID(x_tenant_id)
    except (ValueError, AttributeError):
        logger.warning("public_invalid_tenant_id", raw_value=x_tenant_id[:64])
        raise ValidationError("Invalid tenant ID format") from None
