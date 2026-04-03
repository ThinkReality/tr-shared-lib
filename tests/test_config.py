"""Tests for tr_shared.config.base."""

import pytest
from pydantic import ValidationError

from tr_shared.config.base import BaseServiceSettings

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
        """Downstream services (no SUPABASE_URL) pass without JWKS_URL."""
        s = BaseServiceSettings(**_PROD_BASE)
        assert s.ENVIRONMENT == "production"
        assert s.JWKS_URL == ""

    def test_production_requires_service_token(self):
        with pytest.raises(ValidationError, match="SERVICE_TOKEN"):
            BaseServiceSettings(**{**_PROD_BASE, "SERVICE_TOKEN": ""})

    def test_production_requires_gateway_signing_secret(self):
        with pytest.raises(ValidationError, match="AUTH_LIB_GATEWAY_SIGNING_SECRET"):
            BaseServiceSettings(
                **{**_PROD_BASE, "AUTH_LIB_GATEWAY_SIGNING_SECRET": ""}
            )

    def test_production_requires_auth_lib_service_token(self):
        with pytest.raises(ValidationError, match="AUTH_LIB_SERVICE_TOKEN"):
            BaseServiceSettings(**{**_PROD_BASE, "AUTH_LIB_SERVICE_TOKEN": ""})

    def test_production_rejects_cors_wildcard(self):
        with pytest.raises(ValidationError, match="CORS wildcard"):
            BaseServiceSettings(**{**_PROD_BASE, "CORS_ORIGINS": "*"})

    def test_production_rejects_localhost_redis(self):
        with pytest.raises(ValidationError, match="REDIS_URL.*localhost"):
            BaseServiceSettings(
                **{**_PROD_BASE, "REDIS_URL": "redis://localhost:6379/0"}
            )

    def test_production_rejects_localhost_celery_broker(self):
        with pytest.raises(ValidationError, match="CELERY_BROKER_URL.*localhost"):
            BaseServiceSettings(
                **{**_PROD_BASE, "CELERY_BROKER_URL": "redis://localhost:6379/1"}
            )

    def test_production_rejects_localhost_database(self):
        with pytest.raises(ValidationError, match="DATABASE_URL.*localhost"):
            BaseServiceSettings(
                **{**_PROD_BASE, "DATABASE_URL": "postgresql://localhost:5432/db"}
            )

    def test_development_allows_wildcard(self):
        s = BaseServiceSettings(SERVICE_NAME="svc", CORS_ORIGINS="*")
        assert s.get_cors_origins() == ["*"]

    def test_get_cors_origins_splits_csv(self):
        s = BaseServiceSettings(
            SERVICE_NAME="svc", CORS_ORIGINS="https://a.com, https://b.com"
        )
        assert s.get_cors_origins() == ["https://a.com", "https://b.com"]

    def test_production_valid_config_downstream(self):
        """Downstream service (no Supabase) passes production validation."""
        s = BaseServiceSettings(**_PROD_BASE)
        assert s.ENVIRONMENT == "production"

    def test_production_valid_config_supabase(self):
        """Supabase-enabled service passes production validation."""
        s = BaseServiceSettings(**_PROD_SUPABASE)
        assert s.ENVIRONMENT == "production"
        assert s.JWKS_URL != ""
