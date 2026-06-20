"""S2S contract: tr-crm-core auth/users internal endpoints.

Provider: tr-crm-core auth module (mounted at /api/v1/internal).
Callers: tr-content-platform, tr-whatsApp-marketing-agent, tr-people-finance.
Note: /api/v1/internal/auth-context/* is owned by shared_auth_lib's
AuthContextClient — NOT duplicated here.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

BASE_PATH = "/api/v1/internal"


def user_by_id(user_id: UUID | str) -> str:
    return f"{BASE_PATH}/users/{user_id}"


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
    bayut_user_id: str | None = None
