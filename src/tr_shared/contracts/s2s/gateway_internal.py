"""S2S contract: tr-api-gateway internal cache endpoints consumed by services.

Provider: tr-api-gateway (/api/v1/internal/cache).
Callers: tr-crm-core — webhook-config bust on integration disconnect, and
site-key bust on site rotate / suspend / delete.

The provider does not derive its routes from this module; the paths here are a
copy of the literals in its decorators. `tests/unit/test_s2s_contract_conformance.py`
in tr-api-gateway asserts every builder below resolves to a real registered
route, so the copy cannot drift silently.
"""

BASE_PATH = "/api/v1/internal/cache"


def webhook_config(token: str) -> str:
    return f"{BASE_PATH}/webhook-config/{token}"


def site_key(key_hash: str) -> str:
    """Bust one site-key cache entry. Takes the SHA-256 hash, never the key."""
    return f"{BASE_PATH}/site-key/{key_hash}"
