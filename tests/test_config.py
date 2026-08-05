"""Tests for tr_shared.config.base."""

import pytest
from pydantic import ValidationError

from tr_shared.config.base import SLACK_WEBHOOK_PREFIX, BaseServiceSettings

# Minimal valid production config — reused across tests.
# Does NOT include SUPABASE_URL — downstream services don't need it.
_PROD_BASE = {
    "SERVICE_NAME": "svc",
    "ENVIRONMENT": "production",
    "DATABASE_URL": "postgresql+asyncpg://prod-host:5432/db",
    "SERVICE_TOKEN": "tok",
    "AUTH_LIB_GATEWAY_SIGNING_SECRET": "secret",
    "AUTH_LIB_SERVICE_TOKEN": "s2s-token",
    "REDIS_URL": "redis://prod-redis:6379/0",
    "CELERY_BROKER_URL": "redis://prod-redis:6379/1",
    "CORS_ORIGINS": "https://app.thinkrealty.com",
}

# Production config with Supabase enabled (crm-backend, api-gateway)
_PROD_SUPABASE = {
    **_PROD_BASE,
    "SUPABASE_URL": "https://proj.supabase.co",
    "SUPABASE_JWT_AUDIENCE": "authenticated",
    "JWKS_URL": "https://proj.supabase.co/.well-known/jwks.json",
}


class TestBaseServiceSettings:
    def test_defaults(self):
        s = BaseServiceSettings(SERVICE_NAME="test-svc")
        assert s.SERVICE_NAME == "test-svc"
        assert s.ENVIRONMENT == "development"
        assert s.DATABASE_POOL_SIZE == 5
        assert s.SUPABASE_JWT_AUDIENCE == "authenticated"

    def test_production_requires_database_url(self):
        with pytest.raises(ValidationError, match="DATABASE_URL"):
            BaseServiceSettings(**{**_PROD_BASE, "DATABASE_URL": ""})

    def test_production_requires_jwks_url_when_supabase_set(self):
        with pytest.raises(ValidationError, match="JWKS_URL"):
            BaseServiceSettings(**{**_PROD_SUPABASE, "JWKS_URL": ""})

    def test_production_skips_supabase_validation_without_url(self):
        s = BaseServiceSettings(**_PROD_BASE)
        assert s.ENVIRONMENT == "production"
        assert s.JWKS_URL == ""

    def test_production_requires_service_token(self):
        with pytest.raises(ValidationError, match="SERVICE_TOKEN"):
            BaseServiceSettings(**{**_PROD_BASE, "SERVICE_TOKEN": ""})

    def test_production_requires_gateway_signing_secret(self):
        with pytest.raises(ValidationError, match="AUTH_LIB_GATEWAY_SIGNING_SECRET"):
            BaseServiceSettings(**{**_PROD_BASE, "AUTH_LIB_GATEWAY_SIGNING_SECRET": ""})

    def test_production_requires_auth_lib_service_token(self):
        with pytest.raises(ValidationError, match="AUTH_LIB_SERVICE_TOKEN"):
            BaseServiceSettings(**{**_PROD_BASE, "AUTH_LIB_SERVICE_TOKEN": ""})

    def test_production_rejects_cors_wildcard(self):
        with pytest.raises(ValidationError, match="CORS wildcard"):
            BaseServiceSettings(**{**_PROD_BASE, "CORS_ORIGINS": "*"})

    def test_production_rejects_localhost_redis(self):
        with pytest.raises(ValidationError, match="REDIS_URL.*localhost"):
            BaseServiceSettings(**{**_PROD_BASE, "REDIS_URL": "redis://localhost:6379/0"})

    def test_production_rejects_localhost_celery_broker(self):
        with pytest.raises(ValidationError, match="CELERY_BROKER_URL.*localhost"):
            BaseServiceSettings(**{**_PROD_BASE, "CELERY_BROKER_URL": "redis://localhost:6379/1"})

    def test_production_rejects_localhost_database(self):
        with pytest.raises(ValidationError, match="DATABASE_URL.*localhost"):
            BaseServiceSettings(**{**_PROD_BASE, "DATABASE_URL": "postgresql://localhost:5432/db"})

    def test_development_allows_wildcard(self):
        s = BaseServiceSettings(SERVICE_NAME="svc", CORS_ORIGINS="*")
        assert s.get_cors_origins() == ["*"]

    def test_get_cors_origins_splits_csv(self):
        s = BaseServiceSettings(SERVICE_NAME="svc", CORS_ORIGINS="https://a.com, https://b.com")
        assert s.get_cors_origins() == ["https://a.com", "https://b.com"]

    def test_production_valid_config_downstream(self):
        s = BaseServiceSettings(**_PROD_BASE)
        assert s.ENVIRONMENT == "production"

    def test_production_valid_config_supabase(self):
        s = BaseServiceSettings(**_PROD_SUPABASE)
        assert s.ENVIRONMENT == "production"
        assert s.JWKS_URL != ""


class TestSlackWebhookValidation:
    """A configured error webhook must be real outside dev/test.

    The failure this prevents is silent: a placeholder looks configured, the
    POST 404s, the error handler catches it and logs "Failed to send Slack
    alert", and nobody is alerted. tr-media-service ran that way on stage.
    """

    # Assembled rather than written out. GitHub push protection matches the
    # SHAPE of a Slack webhook, not just known-live values, so even a synthetic
    # literal of the right form is rejected at push time — as this file proved
    # twice. Never write a webhook-shaped literal, and never paste a live one.
    REAL = SLACK_WEBHOOK_PREFIX + "/".join(("T" + "0" * 10, "B" + "0" * 10, "x" * 24))

    def test_the_exact_placeholder_found_on_stage_is_rejected(self):
        with pytest.raises(ValidationError, match="placeholder words"):
            BaseServiceSettings(
                **{
                    **_PROD_BASE,
                    "SLACK_ERROR_WEBHOOK_URL": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
                }
            )

    def test_a_real_webhook_is_accepted(self):
        s = BaseServiceSettings(**{**_PROD_BASE, "SLACK_ERROR_WEBHOOK_URL": self.REAL})
        assert s.SLACK_ERROR_WEBHOOK_URL == self.REAL

    def test_empty_is_allowed_it_means_alerting_is_off(self):
        """Empty is the error handler's own disabled path — not a defect."""
        s = BaseServiceSettings(**{**_PROD_BASE, "SLACK_ERROR_WEBHOOK_URL": ""})
        assert s.SLACK_ERROR_WEBHOOK_URL == ""

    def test_a_non_slack_url_is_rejected(self):
        with pytest.raises(ValidationError, match="does not start with"):
            BaseServiceSettings(
                **{**_PROD_BASE, "SLACK_ERROR_WEBHOOK_URL": "https://example.com/hook"}
            )

    def test_a_truncated_path_is_rejected(self):
        with pytest.raises(ValidationError, match="three non-empty ids"):
            BaseServiceSettings(
                **{
                    **_PROD_BASE,
                    "SLACK_ERROR_WEBHOOK_URL": "https://hooks.slack.com/services/T1/B2",
                }
            )

    def test_staging_is_validated_not_just_production(self):
        """Staging is where the placeholder was actually found."""
        staging = {**_PROD_BASE, "ENVIRONMENT": "staging"}
        with pytest.raises(ValidationError, match="placeholder words"):
            BaseServiceSettings(
                **{
                    **staging,
                    "SLACK_ERROR_WEBHOOK_URL": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
                }
            )

    def test_development_is_not_validated(self):
        """A developer pasting a dummy value must not be blocked from booting."""
        s = BaseServiceSettings(
            SERVICE_NAME="svc",
            ENVIRONMENT="development",
            SLACK_ERROR_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
        )
        assert s.is_local
