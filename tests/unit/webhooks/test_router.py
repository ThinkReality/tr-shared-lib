"""Tests for WebhookRouter."""

from tr_shared.webhooks.router import WebhookRouter
from tr_shared.webhooks.schemas import WebhookEvent


def _make_event(provider: str = "propertyfinder", event_type: str = "listing.published") -> WebhookEvent:
    return WebhookEvent(
        provider=provider,
        event_id="evt-001",
        event_type=event_type,
        raw_body=b"{}",
        payload={},
    )


class TestWebhookRouter:
    async def test_dispatch_calls_registered_handler(self):
        router = WebhookRouter()
        called_with = []

        async def handler(event: WebhookEvent) -> None:
            called_with.append(event)

        router.register("propertyfinder", "listing.published", handler)
        event = _make_event()
        await router.dispatch(event)
        assert len(called_with) == 1
        assert called_with[0].event_id == "evt-001"

    async def test_dispatch_default_handler(self):
        router = WebhookRouter()
        called_with = []

        async def handler(event: WebhookEvent) -> None:
            called_with.append(event)

        router.register_default("propertyfinder", handler)
        event = _make_event(event_type="unknown.event")
        await router.dispatch(event)
        assert len(called_with) == 1

    async def test_exact_match_takes_priority(self):
        router = WebhookRouter()
        exact_calls = []
        default_calls = []

        async def exact_handler(event: WebhookEvent) -> None:
            exact_calls.append(event)

        async def default_handler(event: WebhookEvent) -> None:
            default_calls.append(event)

        router.register("propertyfinder", "listing.published", exact_handler)
        router.register_default("propertyfinder", default_handler)
        await router.dispatch(_make_event(event_type="listing.published"))
        assert len(exact_calls) == 1
        assert len(default_calls) == 0

    async def test_no_handler_logs_warning(self, caplog):
        router = WebhookRouter()
        event = _make_event(provider="unknown_provider")
        with caplog.at_level("WARNING"):
            await router.dispatch(event)
        assert "No handler registered" in caplog.text

    async def test_multiple_providers_independent(self):
        router = WebhookRouter()
        pf_calls = []
        bayut_calls = []

        async def pf_handler(event: WebhookEvent) -> None:
            pf_calls.append(event)

        async def bayut_handler(event: WebhookEvent) -> None:
            bayut_calls.append(event)

        router.register_default("propertyfinder", pf_handler)
        router.register_default("bayut", bayut_handler)

        await router.dispatch(_make_event(provider="propertyfinder"))
        await router.dispatch(_make_event(provider="bayut"))

        assert len(pf_calls) == 1
        assert len(bayut_calls) == 1
