"""Canonical cross-service HTTP header names — the single source of truth.

Every header that crosses a service boundary (gateway → downstream, service →
service, or emitted to clients) is named here exactly once. Consuming code never
writes a raw header string — it references ``HttpHeader.<NAME>`` so a rename
propagates everywhere instead of drifting between sender and reader.

This is the BASE definition: ``tr_shared`` depends on nothing else, so every
library and service can import it. ``shared_auth_lib.SignedHeader`` derives its
values from the identity members here (keeping its HMAC signature-order contract),
and the gateway's ``GatewayHeaders`` does the same.

HTTP header names are case-insensitive on the wire (per RFC 9110 / Starlette
lowercases inbound names), so existing mixed-case reads stay compatible — the
value here is the canonical spelling, not a behavioural change.
"""

from enum import StrEnum


class HttpHeader(StrEnum):
    """Canonical cross-service header names. Reference these, never raw strings."""

    # --- Identity (gateway-signed; shared_auth_lib.SignedHeader derives from these) ---
    USER_ID = "X-User-ID"
    USER_ROLE = "X-User-Role"
    TENANT_ID = "X-Tenant-ID"
    CORRELATION_ID = "X-Correlation-ID"

    # --- Gateway → downstream identity context (read by IdentityExtractionMiddleware) ---
    USER_EMAIL = "X-User-Email"
    USER_PERMISSIONS = "X-User-Permissions"
    AUTH_PROVIDER = "X-Auth-Provider"
    GATEWAY_SIGNATURE = "X-Gateway-Signature"
    GATEWAY_TIMESTAMP = "X-Gateway-Timestamp"

    # --- Service-to-service auth (bypasses HMAC on /internal/* endpoints) ---
    SERVICE_TOKEN = "X-Service-Token"
    # Identifies the calling service on S2S requests (gateway + service clients).
    SERVICE_NAME = "X-Service-Name"
    # Tenant-scoped S2S identity, read by require_internal_service for cross-tenant rejection.
    CALLING_SERVICE = "X-Calling-Service"
    CALLING_TENANT_ID = "X-Calling-Tenant-ID"

    IDEMPOTENCY_KEY = "X-Idempotency-Key"
    IDEMPOTENCY_REPLAYED = "X-Idempotency-Replayed"

    FORWARDED_FOR = "X-Forwarded-For"
    REAL_IP = "X-Real-IP"

    # --- Rate limiting (emitted to clients) ---
    RATE_LIMIT_LIMIT = "X-RateLimit-Limit"
    RATE_LIMIT_REMAINING = "X-RateLimit-Remaining"
    RATE_LIMIT_RESET = "X-RateLimit-Reset"
