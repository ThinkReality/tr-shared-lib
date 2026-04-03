"""Webhook data models and configuration schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class WebhookEvent:
    """Parsed webhook event ready for dispatch.

    Attributes:
        provider: Provider identifier (e.g. ``"propertyfinder"``, ``"meta"``).
        event_id: Unique event identifier from provider or generated UUID.
        event_type: Event type string (e.g. ``"listing.published"``).
        raw_body: Original request body bytes (used for signature verification).
        payload: Parsed JSON payload dict.
        headers: Request headers with lowercased keys.
        tenant_id: Resolved tenant UUID string, or None.
        correlation_id: Correlation ID from request headers.
        received_at: ISO 8601 timestamp when the webhook was received.
        ip_address: Client IP address.
    """

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

    Attributes:
        name: Provider identifier used in URL paths and logging.
        secret: HMAC signing secret. Empty string skips verification.
        signature_header: HTTP header containing the signature.
        signature_format: ``"hex"`` for raw hex digest, ``"sha256={hex}"``
            for prefixed format (used by Bayut/Meta).
        event_id_fields: Ordered list of payload field names to extract event ID from.
        event_type_fields: Ordered list of payload field names to extract event type from.
        idempotency_ttl_seconds: TTL for the idempotency key in Redis.
    """

    name: str
    secret: str = ""
    signature_header: str = "X-Signature"
    signature_format: str = "hex"
    event_id_fields: list[str] = ["eventId", "event_id", "id"]
    event_type_fields: list[str] = ["type", "event", "eventType", "event_type"]
    idempotency_ttl_seconds: int = 86400


class WebhookResult(BaseModel):
    """Response returned to the webhook provider.

    Attributes:
        status: Processing status (``"accepted"``, ``"duplicate"``, ``"error"``).
        event_id: The event ID assigned to this webhook delivery.
        message: Human-readable status message.
    """

    status: str
    event_id: str | None = None
    message: str = "Webhook queued for processing"
