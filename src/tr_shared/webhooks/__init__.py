"""Webhook ingestion framework for ThinkRealty microservices.

Provides:
- Provider-agnostic signature verification (HMAC-SHA256)
- Redis-based idempotency guard (atomic SET NX EX)
- Handler registration and event dispatch
- FastAPI router factory that wires everything together

Concrete provider verifiers for PropertyFinder, Bayut/Dubizzle, and Meta.
"""

from tr_shared.webhooks.endpoint import create_webhook_router
from tr_shared.webhooks.idempotency import WebhookIdempotencyGuard
from tr_shared.webhooks.providers.bayut import BayutMD5Verifier, DubizzleVerifier
from tr_shared.webhooks.providers.meta import MetaWebhookVerifier
from tr_shared.webhooks.providers.propertyfinder import PropertyFinderVerifier
from tr_shared.webhooks.router import WebhookRouter
from tr_shared.webhooks.schemas import ProviderConfig, WebhookEvent, WebhookResult
from tr_shared.webhooks.verifier import HMACVerifier, WebhookVerifier

__all__ = [
    # Factory
    "create_webhook_router",
    # Core
    "WebhookIdempotencyGuard",
    "WebhookRouter",
    # Schemas
    "ProviderConfig",
    "WebhookEvent",
    "WebhookResult",
    # Verifiers
    "WebhookVerifier",
    "HMACVerifier",
    "PropertyFinderVerifier",
    "BayutMD5Verifier",
    "DubizzleVerifier",
    "MetaWebhookVerifier",
]
