"""S2S contract: tr-whatsApp-marketing-agent lead endpoints.

Provider: tr-whatsApp-marketing-agent (mounted at /api/v1/internal/leads).
Caller: tr-lead-management (WAMClient).

The /internal prefix is load-bearing, not cosmetic: WAM mounts
GatewayHMACMiddleware, which 403s any unsigned request outside its skip list,
and /api/v1/internal/ is that skip list's only business-route entry.
"""

from uuid import UUID

BASE_PATH = "/api/v1/internal/leads"


def link() -> str:
    return f"{BASE_PATH}/link"


def start_conversation() -> str:
    return f"{BASE_PATH}/start-conversation"


def close_by_phone() -> str:
    return f"{BASE_PATH}/close-by-phone"


def status(lead_id: UUID | str) -> str:
    return f"{BASE_PATH}/{lead_id}/status"
