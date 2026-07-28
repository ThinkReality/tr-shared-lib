"""The canonical environment vocabulary is a contract. Changing it is a
platform-wide breaking change, so it is frozen here on purpose."""

import pytest

from tr_shared.config.base import BaseServiceSettings
from tr_shared.contracts import Environment


def _settings(env: str) -> BaseServiceSettings:
    """Build settings for `env`, supplying only what the production validator demands."""
    extra: dict[str, str] = {}
    if env == "production":
        extra = {
            "DATABASE_URL": "postgresql+asyncpg://db.internal/x",
            "REDIS_URL": "redis://redis.internal:6379/0",
            "CELERY_BROKER_URL": "redis://redis.internal:6379/1",
            "SERVICE_TOKEN": "t",
            "AUTH_LIB_GATEWAY_SIGNING_SECRET": "s",
            "AUTH_LIB_SERVICE_TOKEN": "t",
        }
    return BaseServiceSettings(SERVICE_NAME="svc", ENVIRONMENT=env, **extra)


class TestVocabularyIsFrozen:
    def test_exactly_four_canonical_values(self):
        assert {e.value for e in Environment} == {
            "development",
            "test",
            "staging",
            "production",
        }

    @pytest.mark.parametrize("banned", ["dev", "local", "prod", "stage", "Production"])
    def test_retired_spellings_are_not_members(self, banned):
        with pytest.raises(ValueError):
            Environment(banned)

    def test_str_renders_as_bare_value(self):
        """Values are concatenated into Redis keys and Loki labels, so the enum
        must render as the plain string, never 'Environment.PRODUCTION'."""
        assert f"{Environment.PRODUCTION}:gateway" == "production:gateway"
        assert Environment.PRODUCTION == "production"


class TestIsLocal:
    def test_development_and_test_are_local(self):
        assert Environment.DEVELOPMENT.is_local is True
        assert Environment.TEST.is_local is True

    def test_staging_and_production_are_not_local(self):
        assert Environment.STAGING.is_local is False
        assert Environment.PRODUCTION.is_local is False


class TestBaseSettingsPredicates:
    def test_is_production(self):
        assert _settings("production").is_production is True
        assert _settings("development").is_production is False

    def test_is_development(self):
        assert _settings("development").is_development is True
        assert _settings("test").is_development is False

    def test_is_local_covers_development_and_test(self):
        assert _settings("development").is_local is True
        assert _settings("test").is_local is True
        assert _settings("staging").is_local is False


class TestInvalidValuesAreRejectedAtStartup:
    """The whole point of the enum. Before this, ENVIRONMENT='prod' booted a
    service with every production guard silently skipped."""

    @pytest.mark.parametrize("bad", ["prod", "dev", "local", "stage", "Production", ""])
    def test_non_canonical_value_raises(self, bad):
        with pytest.raises(ValueError):
            BaseServiceSettings(SERVICE_NAME="svc", ENVIRONMENT=bad)

    def test_canonical_values_are_accepted(self):
        for value in ("development", "test", "staging"):
            assert BaseServiceSettings(SERVICE_NAME="svc", ENVIRONMENT=value).ENVIRONMENT == value
