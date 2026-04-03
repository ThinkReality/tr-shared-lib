"""Tests for WebhookIdempotencyGuard."""

import pytest

from tr_shared.webhooks.idempotency import WebhookIdempotencyGuard


class TestWebhookIdempotencyGuard:
    @pytest.fixture
    def guard(self, async_fake_redis):
        return WebhookIdempotencyGuard(
            redis_client=async_fake_redis,
            key_prefix="test:svc",
            default_ttl=3600,
        )

    async def test_first_event_not_duplicate(self, guard):
        result = await guard.is_duplicate("propertyfinder", "evt-001")
        assert result is False

    async def test_repeated_event_is_duplicate(self, guard):
        await guard.is_duplicate("propertyfinder", "evt-001")
        result = await guard.is_duplicate("propertyfinder", "evt-001")
        assert result is True

    async def test_different_events_not_duplicate(self, guard):
        await guard.is_duplicate("propertyfinder", "evt-001")
        result = await guard.is_duplicate("propertyfinder", "evt-002")
        assert result is False

    async def test_different_providers_independent(self, guard):
        await guard.is_duplicate("propertyfinder", "evt-001")
        result = await guard.is_duplicate("bayut", "evt-001")
        assert result is False

    async def test_empty_event_id_returns_false(self, guard):
        result = await guard.is_duplicate("propertyfinder", "")
        assert result is False

    async def test_key_format(self, guard):
        key = guard.build_key("propertyfinder", "evt-123")
        assert key == "test:svc:webhook:propertyfinder:evt-123:processed"

    async def test_key_format_empty_prefix(self):
        guard = WebhookIdempotencyGuard(key_prefix="")
        key = guard.build_key("meta", "evt-456")
        assert key == "webhook:meta:evt-456:processed"

    async def test_mark_processed(self, guard):
        await guard.mark_processed("propertyfinder", "evt-002")
        result = await guard.is_duplicate("propertyfinder", "evt-002")
        assert result is True

    async def test_mark_processed_empty_event_id(self, guard):
        # Should not raise
        await guard.mark_processed("propertyfinder", "")

    async def test_no_redis_returns_false(self):
        guard = WebhookIdempotencyGuard(redis_client=None, redis_url="")
        result = await guard.is_duplicate("propertyfinder", "evt-001")
        assert result is False

    async def test_custom_ttl_passed_to_set(self, guard, async_fake_redis):
        await guard.is_duplicate("propertyfinder", "ttl-test", ttl=60)
        key = guard.build_key("propertyfinder", "ttl-test")
        ttl_val = await async_fake_redis.ttl(key)
        assert 0 < ttl_val <= 60
