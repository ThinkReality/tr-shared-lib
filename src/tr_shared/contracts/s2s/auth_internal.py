"""S2S contract: tr-crm-core auth/users internal endpoints.

Provider: tr-crm-core auth module (mounted at /api/v1/internal).
Callers: tr-content-platform, tr-whatsApp-marketing-agent, tr-people-finance.
Note: /api/v1/internal/auth-context/* is owned by shared_auth_lib's
AuthContextClient — NOT duplicated here.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tr_shared.contracts.headers import HttpHeader

BASE_PATH = "/api/v1/internal"


def internal_call_headers(calling_service: str, tenant_id: UUID | str) -> dict[str, str]:
    """SSOT for the calling-service + calling-tenant header pair. X-Service-Token is added by each service's HTTP client, not here."""
    return {
        HttpHeader.CALLING_SERVICE.value: calling_service,
        HttpHeader.CALLING_TENANT_ID.value: str(tenant_id),
    }


def user_by_id(user_id: UUID | str) -> str:
    return f"{BASE_PATH}/users/{user_id}"


def tenant_status(tenant_id: UUID | str) -> str:
    return f"{BASE_PATH}/tenant-status/{tenant_id}"


class TenantStatusRef(BaseModel):
    """Caller-facing view of GET /internal/tenant-status/{id} data.

    ``is_active`` folds existence + active flag + soft-delete into one answer:
    a missing, deactivated, or deleted tenant all read as False.
    """

    model_config = ConfigDict(extra="ignore")

    is_active: bool


class UserDetailRef(BaseModel):
    """Lean caller-facing view of GET /internal/users/{id} data.

    The provider's full UserDetailResponse is a superset (drift-tested).
    ``full_name`` is canonical; ``name`` is the provider's alias of it.
    """

    model_config = ConfigDict(extra="ignore")

    id: UUID
    email: str | None = None
    full_name: str | None = None
    name: str | None = None
    department_id: UUID | None = None
    portal_info: dict | None = None
    pf_public_profile_id: str | None = None
    bayut_user_id: int | None = None
