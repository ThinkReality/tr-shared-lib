from uuid import UUID

from fastapi import Header

from tr_shared.contracts.headers import HttpHeader
from tr_shared.exceptions import ValidationError
from tr_shared.logging import get_logger

logger = get_logger(__name__)


async def get_public_tenant_id(
    x_tenant_id: str = Header(
        ...,
        alias=HttpHeader.TENANT_ID.value,
        description="Tenant UUID — required on all public endpoints",
    ),
) -> UUID:
    """No JWT required — UUID format validation only. Public endpoints relying on this
    are expected to be rate-limited separately.
    """
    try:
        return UUID(x_tenant_id)
    except (ValueError, AttributeError):
        logger.warning("public_invalid_tenant_id", raw_value=x_tenant_id[:64])
        raise ValidationError("Invalid tenant ID format") from None
