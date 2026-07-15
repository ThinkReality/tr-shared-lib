"""Webhook data models and configuration schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class WebhookEvent:
    """Parsed webhook event ready for dispatch."""

    provider: str
    event_id: str
    event_type: str
    raw_body: bytes
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    tenant_id: str | None = None
    correlation_id: str | None = None
    received_at: str = ""
    ip_address: str | None = None


class ProviderConfig(BaseModel):
    """Per-provider webhook configuration.

    ``dynamic_secret=True`` invokes the verifier even when ``secret`` is empty;
    the verifier reads the real HMAC secret from a request header (e.g.
    ``X-Webhook-Secret``) instead — used by the PropertyFinder
    gateway-injected-secret flow (Pre-4A).
    """

    name: str
    secret: str = ""
    signature_header: str = "X-Signature"
    signature_format: str = "hex"
    event_id_fields: list[str] = ["eventId", "event_id", "id"]
    event_type_fields: list[str] = ["type", "event", "eventType", "event_type"]
    idempotency_ttl_seconds: int = 86400
    dynamic_secret: bool = False


class WebhookResult(BaseModel):
    """Response returned to the webhook provider."""

    status: str
    event_id: str | None = None
    message: str = "Webhook queued for processing"
