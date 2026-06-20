"""S2S contract: tr-lead-management lead internal endpoints.

Provider: tr-lead-management (mounted at /api/v1/internal/leads).
Callers: tr-crm-core (activity access-check, LeadClient).
Access-check req/resp models live in tr_shared.contracts.s2s.access_check.
"""

from uuid import UUID

BASE_PATH = "/api/v1/internal/leads"


def access_check(lead_id: UUID | str) -> str:
    return f"{BASE_PATH}/{lead_id}/access-check"
