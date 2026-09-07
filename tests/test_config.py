"""Tests for tr_shared.config.base."""

import json

import pytest
from pydantic import ValidationError, field_validator

from tr_shared.config.base import BaseServiceSettings


class _ListValuedCorsSettings(BaseServiceSettings):
    """Mirrors tr-content-platform, the one service whose `CORS_ORIGINS` is a real list.

    It redeclares the field as `str | list[str]` and parses CSV-or-JSON in a
    `mode="before"` validator, which runs before the `mode="after"` model validator —
    so the production check there sees a list, never a string. Testing this against a
    plain `BaseServiceSettings` is not possible: its field is typed `str`, so a list
    argument dies earlier with pydantic's own `string_type` error, whose message
    happens to embed the offending origin and will satisfy a naive `match=`.
    """

    CORS_ORIGINS: str | list[str] = ""  # type: ignore[assignment]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, list):
            return [str(o) for o in v]
        if v.strip().startswith("["):
            return [str(o) for o in json.loads(v)]
        return [o.strip() for o in v.split(",") if o.strip()]


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

    def test_production_rejects_a_localhost_cors_origin(self):
        """The gap this closes. Every one of the six services carrying a
        `CORS_ORIGINS` today lists `http://localhost:3000`, and with
        `allow_credentials=True` that is a standing trust grant to anything on a
        signed-in user's machine. Nothing rejected it before: the wildcard check
        looks only for `*`, and the localhost check covers only REDIS_URL,
        CELERY_BROKER_URL and DATABASE_URL.
        """
        with pytest.raises(ValidationError, match="http://localhost:3000"):
            BaseServiceSettings(
                **{
                    **_PROD_BASE,
                    "CORS_ORIGINS": "https://app.thinkrealty.com,http://localhost:3000",
                }
            )

    @pytest.mark.parametrize(
        "origin",
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://[::1]:3000",
            "http://10.0.0.7",
            "http://app.thinkrealty.com",
        ],
    )
    def test_production_rejects_every_non_https_origin(self, origin):
        """Scheme, not a loopback allowlist — plain http to a real host is the same
        mistake and would slip past a `localhost`/`127.0.0.1` substring check."""
        with pytest.raises(ValidationError, match="must be https"):
            BaseServiceSettings(**{**_PROD_BASE, "CORS_ORIGINS": origin})

    def test_production_accepts_several_https_origins(self):
        """Guards against the check being satisfied by rejecting everything."""
        s = BaseServiceSettings(
            **{
                **_PROD_BASE,
                "CORS_ORIGINS": "https://app.thinkrealty.com, https://stage.proplytics.ae",
            }
        )
        assert s.ENVIRONMENT == "production"

    def test_a_list_valued_cors_origins_is_checked_too(self):
        """The check must not be built on `get_cors_origins()`, which assumes the string
        shape and raises `AttributeError` on a list — that would silently skip the one
        service whose deployed value is a JSON array.

        This must run against `_ListValuedCorsSettings`, not `BaseServiceSettings`: the
        base field is typed `str`, so a list argument dies earlier with pydantic's own
        `string_type` error, whose message embeds the offending origin and will satisfy
        a naive `match="http://localhost:3000"`. That is exactly how the first version
        of this test passed while the check it named was bypassed.
        """
        with pytest.raises(ValidationError, match="must be https"):
            _ListValuedCorsSettings(
                **{
                    **_PROD_BASE,
                    "CORS_ORIGINS": '["https://app.thinkrealty.com", "http://localhost:3000"]',
                }
            )

    def test_a_list_valued_cors_origins_accepts_all_https(self):
        """Negative control for the test above: it must fail on the origin, not on the
        list shape itself."""
        s = _ListValuedCorsSettings(
            **{
                **_PROD_BASE,
                "CORS_ORIGINS": '["https://app.thinkrealty.com", "https://stage.proplytics.ae"]',
            }
        )

        assert s.CORS_ORIGINS == ["https://app.thinkrealty.com", "https://stage.proplytics.ae"]

    @pytest.mark.parametrize("environment", ["development", "test", "staging"])
    def test_a_localhost_origin_is_fine_outside_production(self, environment):
        """Local frontend development against a deployed API is the reason these
        entries exist; only production may not carry them."""
        s = BaseServiceSettings(
            **{**_PROD_BASE, "ENVIRONMENT": environment, "CORS_ORIGINS": "http://localhost:3000"}
        )
        assert s.get_cors_origins() == ["http://localhost:3000"]

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
