"""FastAPI router factory for webhook ingestion endpoints.

Generates ``POST /{provider}`` and ``GET /{provider}/health`` endpoints
for each configured provider. For Meta providers, also generates a
``GET /{provider}`` endpoint to handle the verification handshake.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from tr_shared.webhooks.idempotency import WebhookIdempotencyGuard
from tr_shared.webhooks.providers.meta import MetaWebhookVerifier
from tr_shared.webhooks.router import WebhookRouter
from tr_shared.webhooks.schemas import ProviderConfig, WebhookEvent, WebhookResult
from tr_shared.webhooks.verifier import WebhookVerifier

logger = logging.getLogger(__name__)

# Tenant resolver callable type:
# (provider, headers, payload) -> tenant_id or None
TenantResolver = Callable[[str, dict[str, str], dict[str, Any]], str | None]


def _extract_field(payload: dict[str, Any], field_names: list[str]) -> str:
    """Extract the first matching field from a payload dict."""
    for name in field_names:
        value = payload.get(name)
        if value is not None:
            return str(value)
    return ""


def _get_client_ip(request: Request) -> str | None:
    """Extract client IP from request, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def create_webhook_router(
    *,
    provider_configs: list[ProviderConfig],
    verifiers: dict[str, WebhookVerifier] | None = None,
    idempotency_guard: WebhookIdempotencyGuard | None = None,
    event_producer: Any | None = None,
    webhook_router: WebhookRouter | None = None,
    rate_limiter: Any | None = None,
    rate_limit_config: Any | None = None,
    tenant_resolver: TenantResolver | None = None,
    response_status_code: int = 202,
) -> APIRouter:
    """Create a FastAPI router with webhook endpoints for each provider.

    For each :class:`ProviderConfig`, generates:

    - ``POST /{provider_name}`` — receive and verify webhook
    - ``GET /{provider_name}/health`` — provider-specific health check

    If the verifier for a provider is a :class:`MetaWebhookVerifier`, also
    generates ``GET /{provider_name}`` for the verification handshake.

    Request flow:

    1. Read raw body
    2. Verify signature (if secret configured) → 401 on failure
    3. Parse JSON → 400 on failure
    4. Extract event_id / event_type from payload
    5. Resolve tenant_id via custom resolver or ``X-Tenant-ID`` header
    6. Idempotency check → 200 with duplicate status if seen before
    7. Publish to EventProducer (if configured)
    8. Dispatch to WebhookRouter (if configured)
    9. Return configured status code with :class:`WebhookResult`

    Args:
        provider_configs: List of provider configurations.
        verifiers: Map of provider name → verifier instance. If not provided
            for a provider, signature verification is skipped.
        idempotency_guard: Optional idempotency guard for deduplication.
        event_producer: Optional ``EventProducer`` for publishing to Redis Streams.
        webhook_router: Optional router for dispatching to handlers.
        rate_limiter: Optional ``RateLimiter`` instance.
        rate_limit_config: Optional ``RateLimitConfig`` for the rate limiter.
        tenant_resolver: Optional callable ``(provider, headers, payload) -> tenant_id``.
        response_status_code: HTTP status code for successful responses (default 202).

    Returns:
        A configured FastAPI ``APIRouter``.
    """
    router = APIRouter()
    verifiers = verifiers or {}
    config_map: dict[str, ProviderConfig] = {c.name: c for c in provider_configs}

    for config in provider_configs:
        _register_provider_endpoints(
            router=router,
            config=config,
            verifiers=verifiers,
            config_map=config_map,
            idempotency_guard=idempotency_guard,
            event_producer=event_producer,
            webhook_router=webhook_router,
            rate_limiter=rate_limiter,
            rate_limit_config=rate_limit_config,
            tenant_resolver=tenant_resolver,
            response_status_code=response_status_code,
        )

    return router


def _register_provider_endpoints(
    *,
    router: APIRouter,
    config: ProviderConfig,
    verifiers: dict[str, WebhookVerifier],
    config_map: dict[str, ProviderConfig],
    idempotency_guard: WebhookIdempotencyGuard | None,
    event_producer: Any | None,
    webhook_router: WebhookRouter | None,
    rate_limiter: Any | None,
    rate_limit_config: Any | None,
    tenant_resolver: TenantResolver | None,
    response_status_code: int,
) -> None:
    """Register POST, GET/health, and optional GET handshake for a provider."""
    provider_name = config.name
    verifier = verifiers.get(provider_name)

    # --- POST /{provider_name} ---
    @router.post(
        f"/{provider_name}",
        status_code=response_status_code,
        summary=f"{provider_name} webhook",
        name=f"webhook_{provider_name}_post",
    )
    async def receive_webhook(request: Request, _pn: str = provider_name) -> Response:
        pn = _pn
        cfg = config_map[pn]
        vrf = verifiers.get(pn)

        # Rate limit check
        if rate_limiter and rate_limit_config:
            try:
                ip = _get_client_ip(request)
                key = rate_limiter.build_key(
                    identifier=ip or "unknown",
                    endpoint=f"webhook_{pn}",
                    scope="webhook",
                )
                result = await rate_limiter.check(key, rate_limit_config)
                if not result.allowed:
                    return JSONResponse(
                        status_code=429,
                        content={"error": "Rate limit exceeded"},
                        headers={
                            "X-RateLimit-Limit": str(result.limit),
                            "X-RateLimit-Remaining": str(result.remaining),
                            "X-RateLimit-Reset": str(result.reset_at),
                        },
                    )
            except Exception:
                logger.warning("Rate limit check failed — allowing request", exc_info=True)

        # Read raw body once
        raw_body = await request.body()

        # Build lowercased headers dict
        headers = {k.lower(): v for k, v in request.headers.items()}

        # Verify signature.
        # Pre-4A: when ``cfg.dynamic_secret`` is True, invoke the verifier
        # even if ``cfg.secret`` is empty — the verifier is expected to
        # read the real HMAC secret from a request header (e.g.
        # ``X-Webhook-Secret`` injected by the API gateway for PF).
        if vrf and (cfg.secret or cfg.dynamic_secret):
            if not vrf.verify(raw_body, headers, cfg.secret):
                logger.warning("Invalid webhook signature: provider=%s", pn)
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid webhook signature"},
                )

        # Parse JSON
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON payload"},
            )

        # Extract event_id and event_type
        event_id = _extract_field(payload, cfg.event_id_fields) or str(uuid4())
        event_type = _extract_field(payload, cfg.event_type_fields) or "unknown"

        # Resolve tenant_id
        tenant_id: str | None = None
        if tenant_resolver:
            tenant_id = tenant_resolver(pn, headers, payload)
        if not tenant_id:
            tenant_id = headers.get("x-tenant-id")

        # Idempotency check
        if idempotency_guard:
            is_dup = await idempotency_guard.is_duplicate(
                pn,
                event_id,
                ttl=cfg.idempotency_ttl_seconds,
            )
            if is_dup:
                logger.info("Duplicate webhook skipped: provider=%s, event_id=%s", pn, event_id)
                return JSONResponse(
                    status_code=200,
                    content=WebhookResult(
                        status="duplicate",
                        event_id=event_id,
                        message="Duplicate webhook — already processed",
                    ).model_dump(),
                )

        # Build webhook event
        correlation_id = headers.get("x-correlation-id")
        event = WebhookEvent(
            provider=pn,
            event_id=event_id,
            event_type=event_type,
            raw_body=raw_body,
            payload=payload,
            headers=headers,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            received_at=datetime.now(UTC).isoformat(),
            ip_address=_get_client_ip(request),
        )

        # Publish to event bus
        if event_producer:
            try:
                await event_producer.publish(
                    event_type=f"webhook.{pn}.received",
                    tenant_id=tenant_id or "",
                    data={
                        "provider": pn,
                        "event_id": event_id,
                        "event_type": event_type,
                        "payload": payload,
                    },
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning("Failed to publish webhook event to stream", exc_info=True)

        # Dispatch to handler
        if webhook_router:
            try:
                await webhook_router.dispatch(event)
            except Exception:
                logger.exception(
                    "Webhook handler error: provider=%s, event_id=%s",
                    pn,
                    event_id,
                )

        return JSONResponse(
            status_code=response_status_code,
            content=WebhookResult(
                status="accepted",
                event_id=event_id,
                message="Webhook queued for processing",
            ).model_dump(),
        )

    # --- GET /{provider_name}/health ---
    @router.get(
        f"/{provider_name}/health",
        status_code=200,
        summary=f"{provider_name} webhook health",
        name=f"webhook_{provider_name}_health",
    )
    async def health_check(_pn: str = provider_name) -> dict[str, str]:
        return {
            "status": "healthy",
            "provider": _pn,
            "endpoint": f"webhook_{_pn}",
        }

    # --- GET /{provider_name} (Meta handshake) ---
    if isinstance(verifier, MetaWebhookVerifier):
        _meta_verifier = verifier

        @router.get(
            f"/{provider_name}",
            status_code=200,
            response_model=None,
            summary=f"{provider_name} verification handshake",
            name=f"webhook_{provider_name}_handshake",
        )
        async def meta_handshake(request: Request) -> Response:
            query_params = dict(request.query_params)
            challenge = _meta_verifier.handle_handshake(query_params)
            if challenge is not None:
                return PlainTextResponse(str(challenge))
            return JSONResponse(
                status_code=403,
                content={"error": "Verification failed"},
            )
