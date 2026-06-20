"""S2S contract: tr-api-gateway internal cache endpoints consumed by services.

Provider: tr-api-gateway (/api/v1/internal/cache).
Caller: tr-crm-core (admin webhook-config cache bust on integration disconnect).
"""

BASE_PATH = "/api/v1/internal/cache"


def webhook_config(token: str) -> str:
    return f"{BASE_PATH}/webhook-config/{token}"
