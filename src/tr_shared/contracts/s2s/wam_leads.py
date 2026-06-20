"""S2S contract: tr-whatsApp-marketing-agent lead endpoints.

Provider: tr-whatsApp-marketing-agent (mounted at /api/v1/leads).
Caller: tr-lead-management (WAMClient).
"""

from uuid import UUID

BASE_PATH = "/api/v1/leads"


def link() -> str:
    return f"{BASE_PATH}/link"


def start_conversation() -> str:
    return f"{BASE_PATH}/start-conversation"


def close_by_phone() -> str:
    return f"{BASE_PATH}/close-by-phone"


def status(lead_id: UUID | str) -> str:
    return f"{BASE_PATH}/{lead_id}/status"
