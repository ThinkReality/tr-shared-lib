"""Base settings class for all ThinkRealty services."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tr_shared.contracts.environment import Environment


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    SERVICE_NAME: str
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" in production

    DATABASE_URL: str = ""
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    # ── Supabase Auth (optional — only required by services that talk to
    # Supabase directly, e.g. crm-backend and tr-api-gateway) ──
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    JWKS_URL: str = ""
    SERVICE_TOKEN: str = ""

    REDIS_URL: str = "redis://localhost:6379/0"

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_TIME_LIMIT: int = 600
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1

    AUTH_LIB_GATEWAY_SIGNING_SECRET: str = ""
    AUTH_LIB_CRM_CORE_URL: str = "http://tr-crm-core:8000"
    AUTH_LIB_SERVICE_TOKEN: str = ""

    # ── Vault Secret Resolution (optional — empty = use plain env var) ──
    # Set these to Vault secret UUIDs at deploy time; leave empty for local dev.
    # ONLY these two resolve: vault.py's secret_map is an explicit dict, so a *_VAULT_UUID
    # field with no entry there is inert. A third, SERVICE_TOKEN_VAULT_UUID, was declared
    # here but absent from that map — it promised Vault resolution of the inbound
    # SERVICE_TOKEN and silently delivered none. Removed 2026-08-10. If SERVICE_TOKEN
    # should be vault-backed, add it to the map first; the field alone does nothing.
    AUTH_LIB_GATEWAY_SIGNING_SECRET_VAULT_UUID: str = ""
    AUTH_LIB_SERVICE_TOKEN_VAULT_UUID: str = ""

    EVENT_STREAM_NAME: str = "tr_event_bus"
    CONSUMER_GROUP_NAME: str = ""
    CONSUMER_NAME: str = "worker_1"
    EVENT_BATCH_SIZE: int = 10
    EVENT_BLOCK_MS: int = 5000

    CORS_ORIGINS: str = ""

    SLACK_ERROR_WEBHOOK_URL: str = ""

    METRICS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090
    ENABLE_TRACING: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    LOKI_URL: str = ""

    def get_cors_origins(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        return origins

    def _cors_origin_list(self) -> list[str]:
        """Normalises both shapes `CORS_ORIGINS` arrives in.

        It is a comma-separated string in seven services, but tr-content-platform
        redeclares it as `str | list[str]` and parses CSV-or-JSON in a
        `mode="before"` validator, so by the time this model validator runs it
        already holds a real list there. `get_cors_origins()` above assumes the
        string and would raise `AttributeError` on that service — which is why
        this exists rather than reusing it.
        """
        raw = self.CORS_ORIGINS
        if isinstance(raw, str):
            return [o.strip() for o in raw.split(",") if o.strip()]
        return [str(o).strip() for o in raw if str(o).strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == Environment.DEVELOPMENT

    @property
    def is_local(self) -> bool:
        """Developer machine or test run — the only place guards may relax."""
        return self.ENVIRONMENT in (Environment.DEVELOPMENT, Environment.TEST)

    @model_validator(mode="after")
    def validate_production_config(self) -> "BaseServiceSettings":
        if self.is_production:
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL required in production")
            # Supabase fields are only required when SUPABASE_URL is set
            # (i.e. services that talk to Supabase directly: crm-backend,
            # tr-api-gateway). Downstream services using shared-auth-lib
            # gateway HMAC do NOT need these.
            if self.SUPABASE_URL:
                if not self.SUPABASE_JWT_AUDIENCE:
                    raise ValueError("SUPABASE_JWT_AUDIENCE required when SUPABASE_URL is set")
                if not self.JWKS_URL:
                    raise ValueError("JWKS_URL required when SUPABASE_URL is set")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS wildcard not allowed in production")
            # A CORS origin is a trust grant, and `allow_credentials=True` is set
            # fleet-wide, so a surviving `http://localhost:3000` lets anything on a
            # signed-in user's machine read production responses. Scheme rather than
            # a loopback list: `localhost`, `127.0.0.1`, `[::1]` and a plain-http LAN
            # host are the same mistake, and an allowlist of spellings goes stale.
            insecure_origins = [
                origin for origin in self._cors_origin_list() if not origin.startswith("https://")
            ]
            if insecure_origins:
                raise ValueError(
                    "CORS_ORIGINS must be https:// in production; remove or replace: "
                    + ", ".join(insecure_origins)
                )
            if not self.SERVICE_TOKEN:
                raise ValueError("SERVICE_TOKEN required in production")
            if not self.AUTH_LIB_GATEWAY_SIGNING_SECRET:
                raise ValueError("AUTH_LIB_GATEWAY_SIGNING_SECRET required in production")
            if not self.AUTH_LIB_SERVICE_TOKEN:
                raise ValueError("AUTH_LIB_SERVICE_TOKEN required in production")
            for url_field in ("REDIS_URL", "CELERY_BROKER_URL", "DATABASE_URL"):
                value = getattr(self, url_field)
                if value and "localhost" in value:
                    raise ValueError(f"{url_field} must not point to localhost in production")
        return self
