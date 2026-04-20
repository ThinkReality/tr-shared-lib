"""Base settings class for all ThinkRealty services."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Service Identity ──
    SERVICE_NAME: str
    ENVIRONMENT: str = "development"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" in production

    # ── Database ──
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

    # ── Redis ──
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Celery ──
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_TIME_LIMIT: int = 600
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1

    # ── shared-auth-lib ──
    AUTH_LIB_GATEWAY_SIGNING_SECRET: str = ""
    AUTH_LIB_CRM_BACKEND_URL: str = "http://crm-backend:8000"
    AUTH_LIB_ADMIN_PANEL_URL: str = "http://tr-be-admin-panel:8003"
    AUTH_LIB_SERVICE_TOKEN: str = ""

    # ── Vault Secret Resolution (optional — empty = use plain env var) ──
    # Set these to Vault secret UUIDs at deploy time; leave empty for local dev.
    AUTH_LIB_GATEWAY_SIGNING_SECRET_VAULT_UUID: str = ""
    AUTH_LIB_SERVICE_TOKEN_VAULT_UUID: str = ""
    SERVICE_TOKEN_VAULT_UUID: str = ""  # CRM-backend: UUID for its own incoming SERVICE_TOKEN

    # ── Event Bus ──
    EVENT_STREAM_NAME: str = "tr_event_bus"
    CONSUMER_GROUP_NAME: str = ""
    CONSUMER_NAME: str = "worker_1"
    EVENT_BATCH_SIZE: int = 10
    EVENT_BLOCK_MS: int = 5000

    # ── CORS ──
    CORS_ORIGINS: str = ""

    # ── Slack Alerts ──
    SLACK_ERROR_WEBHOOK_URL: str = ""

    # ── Monitoring (Layer 1: Prometheus/OTel) ──
    METRICS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090
    ENABLE_TRACING: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    # ── Monitoring (Layer 2: persistence to central DB) ──
    MONITORING_ENABLED: bool = False
    MONITORING_DB_URL: str = ""
    LOKI_URL: str = ""

    def get_cors_origins(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        return origins

    @model_validator(mode="after")
    def validate_production_config(self) -> "BaseServiceSettings":
        if self.ENVIRONMENT == "production":
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL required in production")
            # Supabase fields are only required when SUPABASE_URL is set
            # (i.e. services that talk to Supabase directly: crm-backend,
            # tr-api-gateway). Downstream services using shared-auth-lib
            # gateway HMAC do NOT need these.
            if self.SUPABASE_URL:
                if not self.SUPABASE_JWT_AUDIENCE:
                    raise ValueError(
                        "SUPABASE_JWT_AUDIENCE required when SUPABASE_URL is set"
                    )
                if not self.JWKS_URL:
                    raise ValueError(
                        "JWKS_URL required when SUPABASE_URL is set"
                    )
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS wildcard not allowed in production")
            if not self.SERVICE_TOKEN:
                raise ValueError("SERVICE_TOKEN required in production")
            if not self.AUTH_LIB_GATEWAY_SIGNING_SECRET:
                raise ValueError(
                    "AUTH_LIB_GATEWAY_SIGNING_SECRET required in production"
                )
            if not self.AUTH_LIB_SERVICE_TOKEN:
                raise ValueError("AUTH_LIB_SERVICE_TOKEN required in production")
            for url_field in ("REDIS_URL", "CELERY_BROKER_URL", "DATABASE_URL"):
                value = getattr(self, url_field)
                if value and "localhost" in value:
                    raise ValueError(
                        f"{url_field} must not point to localhost in production"
                    )
        return self
