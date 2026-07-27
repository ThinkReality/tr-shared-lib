"""Canonical deployment-environment names — the single source of truth.

Every service and library names its deployment environment from this enum. It
exists because the platform previously accepted nine spellings of four concepts
(``dev``, ``development``, ``local``, ``test``, ``staging``, ``prod``, ``stage``,
``production``, ``Production``) and the guards that read them disagreed:

* ``BaseServiceSettings`` fired its production checks on the exact string
  ``"production"``, so ``ENVIRONMENT=prod`` booted a service with **every**
  production guard skipped — empty ``DATABASE_URL``, wildcard CORS, blank
  ``SERVICE_TOKEN`` and localhost Redis all silently accepted.
* Two consumers treated ``prod``/``stage`` as production while the rest did not,
  so one string meant opposite things in different services.
* Six Python "is this a dev box?" sets existed, one of them commented as
  mirroring another, plus ten more branches in shell entrypoints.

Values are lowercase full words. Lowercase because these strings are
concatenated into Redis key prefixes (``f"{ENVIRONMENT}:gateway"``) and used as
Loki stream labels, both case-sensitive. Full words because fourteen production
validators across eight services already compare against the literal
``"production"`` — abbreviating would mean rewriting every production guard on
the platform to save four characters.

There are deliberately no aliases and no normalization helper. An unrecognised
value must fail loudly at startup, because the alternative is the silent
fail-open above.
"""

from enum import StrEnum


class Environment(StrEnum):
    """The only valid values for the ``ENVIRONMENT`` variable, platform-wide."""

    DEVELOPMENT = "development"
    """Developer machines and docker-compose.dev.local.yml."""

    TEST = "test"
    """pytest runs only. Load-bearing: tr-crm-core swaps the SQLAlchemy engine to
    NullPool here, because pytest-asyncio gives each test its own event loop and
    a pooled asyncpg connection cannot cross loops."""

    STAGING = "staging"
    """Pre-production. Holds its own Supabase DB and Redis, isolated from prod."""

    PRODUCTION = "production"
    """Live. Enables every production validator in BaseServiceSettings."""

    @property
    def is_local(self) -> bool:
        """True on a developer machine or in a test run.

        The ONE definition of "local enough to relax a guard" — most importantly
        the dev auth bypass. It lives on the enum rather than on
        BaseServiceSettings so shared-auth-lib, whose AuthLibSettings does not
        inherit from BaseServiceSettings, uses the same rule instead of keeping
        its own copy.
        """
        return self in (Environment.DEVELOPMENT, Environment.TEST)
