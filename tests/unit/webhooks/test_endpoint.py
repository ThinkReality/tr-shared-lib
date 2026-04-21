"""Tests for create_webhook_router endpoint factory."""

import hashlib
import hmac
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tr_shared.webhooks.endpoint import create_webhook_router
from tr_shared.webhooks.idempotency import WebhookIdempotencyGuard
from tr_shared.webhooks.providers.meta import MetaWebhookVerifier
from tr_shared.webhooks.providers.propertyfinder import PropertyFinderVerifier
from tr_shared.webhooks.router import WebhookRouter
from tr_shared.webhooks.schemas import ProviderConfig, WebhookEvent

SECRET = "test-secret-32-characters-long!"
PAYLOAD = {"event": "listing.published", "id": "lst-001", "listingId": "42"}
BODY = json.dumps(PAYLOAD).encode()


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _build_app(
    configs: list[ProviderConfig] | None = None,
    verifiers: dict | None = None,
    idempotency_guard: WebhookIdempotencyGuard | None = None,
    webhook_router: WebhookRouter | None = None,
    response_status_code: int = 202,
    tenant_resolver=None,
) -> FastAPI:
    app = FastAPI()
    configs = configs or [ProviderConfig(name="propertyfinder", secret=SECRET)]
    verifiers = verifiers or {"propertyfinder": PropertyFinderVerifier()}
    router = create_webhook_router(
        provider_configs=configs,
        verifiers=verifiers,
        idempotency_guard=idempotency_guard,
        webhook_router=webhook_router,
        tenant_resolver=tenant_resolver,
        response_status_code=response_status_code,
    )
    app.include_router(router, prefix="/webhooks")
    return app


class TestWebhookEndpointPost:
    def test_valid_signature_returns_configured_status(self):
        app = _build_app()
        client = TestClient(app)
        sig = _sign(BODY, SECRET)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["event_id"] == "lst-001"

    def test_custom_response_status_code(self):
        app = _build_app(response_status_code=200)
        client = TestClient(app)
        sig = _sign(BODY, SECRET)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    def test_invalid_signature_returns_401(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"X-Signature": "bad-signature", "Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_no_secret_configured_skips_verification(self):
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
            verifiers={"propertyfinder": PropertyFinderVerifier()},
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 202

    def test_invalid_json_returns_400(self):
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_extracts_event_type_from_payload(self):
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp.json()["event_id"] == "lst-001"

    def test_extracts_type_field_for_pf_envelope(self):
        """PF sends event type in 'type' field (base envelope format)."""
        pf_body = json.dumps({
            "id": "evt-uuid-001",
            "type": "lead.created",
            "timestamp": "2025-08-24T14:15:22Z",
            "entity": {"id": "lead-123", "type": "lead"},
            "payload": {"channel": "whatsapp"},
        }).encode()
        dispatched = []

        async def handler(event: WebhookEvent) -> None:
            dispatched.append(event)

        wr = WebhookRouter()
        wr.register_default("propertyfinder", handler)
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
            webhook_router=wr,
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=pf_body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 202
        assert dispatched[0].event_type == "lead.created"
        assert dispatched[0].event_id == "evt-uuid-001"

    def test_tenant_id_from_header(self):
        dispatched = []

        async def handler(event: WebhookEvent) -> None:
            dispatched.append(event)

        wr = WebhookRouter()
        wr.register_default("propertyfinder", handler)
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
            webhook_router=wr,
        )
        client = TestClient(app)
        client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json", "X-Tenant-ID": "tenant-uuid"},
        )
        assert len(dispatched) == 1
        assert dispatched[0].tenant_id == "tenant-uuid"

    def test_custom_tenant_resolver(self):
        dispatched = []

        async def handler(event: WebhookEvent) -> None:
            dispatched.append(event)

        def resolver(provider, headers, payload):
            return "custom-tenant"

        wr = WebhookRouter()
        wr.register_default("propertyfinder", handler)
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
            webhook_router=wr,
            tenant_resolver=resolver,
        )
        client = TestClient(app)
        client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert dispatched[0].tenant_id == "custom-tenant"

    def test_dispatches_to_webhook_router(self):
        dispatched = []

        async def handler(event: WebhookEvent) -> None:
            dispatched.append(event)

        wr = WebhookRouter()
        wr.register_default("propertyfinder", handler)
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
            webhook_router=wr,
        )
        client = TestClient(app)
        client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert len(dispatched) == 1
        assert dispatched[0].provider == "propertyfinder"
        assert dispatched[0].event_type == "listing.published"


class TestWebhookEndpointIdempotency:
    def test_duplicate_event_returns_200(self, async_fake_redis):
        guard = WebhookIdempotencyGuard(redis_client=async_fake_redis, key_prefix="test")
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
            idempotency_guard=guard,
        )
        client = TestClient(app)

        # First request
        resp1 = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp1.status_code == 202
        assert resp1.json()["status"] == "accepted"

        # Second request (duplicate)
        resp2 = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "duplicate"


class TestWebhookEndpointHealth:
    def test_health_endpoint(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/webhooks/propertyfinder/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["provider"] == "propertyfinder"


class TestMetaHandshake:
    def test_valid_handshake_echos_challenge(self):
        verifier = MetaWebhookVerifier(verify_token="my-token")
        app = _build_app(
            configs=[ProviderConfig(name="meta", secret="app-secret")],
            verifiers={"meta": verifier},
        )
        client = TestClient(app)
        resp = client.get(
            "/webhooks/meta",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "my-token",
                "hub.challenge": "98765",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "98765"

    def test_invalid_handshake_returns_403(self):
        verifier = MetaWebhookVerifier(verify_token="my-token")
        app = _build_app(
            configs=[ProviderConfig(name="meta", secret="app-secret")],
            verifiers={"meta": verifier},
        )
        client = TestClient(app)
        resp = client.get(
            "/webhooks/meta",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "98765",
            },
        )
        assert resp.status_code == 403

    def test_meta_post_with_valid_signature(self):
        meta_body = json.dumps({"object": "page", "entry": [{"id": "123", "time": 1}]}).encode()
        digest = hmac.new(b"app-secret", meta_body, hashlib.sha256).hexdigest()
        sig = f"sha256={digest}"

        verifier = MetaWebhookVerifier(verify_token="my-token")
        app = _build_app(
            configs=[ProviderConfig(
                name="meta",
                secret="app-secret",
                event_id_fields=["id"],
                event_type_fields=["object"],
            )],
            verifiers={"meta": verifier},
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/meta",
            content=meta_body,
            headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 202


class TestMultipleProviders:
    def test_multiple_providers_on_same_router(self):
        app = _build_app(
            configs=[
                ProviderConfig(name="propertyfinder", secret=""),
                ProviderConfig(name="bayut", secret=""),
            ],
            verifiers={},
        )
        client = TestClient(app)

        resp1 = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp1.status_code == 202

        resp2 = client.post(
            "/webhooks/bayut",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp2.status_code == 202


# ──────────────────────────────────────────────────────────────────────
# Batch Pre-4A — ``dynamic_secret`` flag contract
#
# spec: docs/specs/04-batch-downstream-handlers.md §Pre-4A.
# ──────────────────────────────────────────────────────────────────────


class _StubVerifier:
    """Verifier that records every call and returns a configurable result.

    Lets us assert whether the framework invokes the verifier under each
    (secret, dynamic_secret) combination — the whole point of Pre-4A.
    """

    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[bytes, dict, str]] = []
        self.result = result

    def verify(self, raw_body: bytes, headers: dict, secret: str) -> bool:
        self.calls.append((raw_body, headers, secret))
        return self.result


class TestDynamicSecretFlag:
    def test_default_dynamic_secret_false(self):
        cfg = ProviderConfig(name="propertyfinder")
        assert cfg.dynamic_secret is False

    def test_secret_empty_dynamic_false_skips_verification(self):
        """Legacy behavior: empty secret + default flag → verifier NOT invoked."""
        vrf = _StubVerifier(result=False)
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret="")],
            verifiers={"propertyfinder": vrf},
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        # No verifier call → no 401 regardless of verifier's configured result.
        assert resp.status_code == 202
        assert vrf.calls == []

    def test_secret_empty_dynamic_true_invokes_verifier_and_401s_on_false(self):
        """Pre-4A: empty secret + dynamic_secret=True → verifier IS invoked."""
        vrf = _StubVerifier(result=False)
        app = _build_app(
            configs=[
                ProviderConfig(
                    name="propertyfinder",
                    secret="",
                    dynamic_secret=True,
                ),
            ],
            verifiers={"propertyfinder": vrf},
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        assert len(vrf.calls) == 1
        # The framework passes the (empty) ``cfg.secret`` through — the
        # verifier is expected to ignore it and read the real secret from
        # headers (e.g. X-Webhook-Secret).
        assert vrf.calls[0][2] == ""

    def test_secret_empty_dynamic_true_verifier_true_yields_success(self):
        vrf = _StubVerifier(result=True)
        app = _build_app(
            configs=[
                ProviderConfig(
                    name="propertyfinder",
                    secret="",
                    dynamic_secret=True,
                ),
            ],
            verifiers={"propertyfinder": vrf},
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 202
        assert len(vrf.calls) == 1

    def test_secret_set_behavior_unchanged(self):
        """Static-secret path: dynamic_secret default is False; verifier invoked
        with the configured secret. Guards against regression of the existing
        Bayut/Meta/Dubizzle static-secret path.
        """
        vrf = _StubVerifier(result=True)
        app = _build_app(
            configs=[ProviderConfig(name="propertyfinder", secret=SECRET)],
            verifiers={"propertyfinder": vrf},
        )
        client = TestClient(app)
        sig = _sign(BODY, SECRET)
        resp = client.post(
            "/webhooks/propertyfinder",
            content=BODY,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 202
        assert len(vrf.calls) == 1
        assert vrf.calls[0][2] == SECRET
