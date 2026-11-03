"""Per-service test configuration, read from ``[tool.tr_testing]`` in pyproject.

The plugin ships as a ``pytest11`` entry point, so it is loaded in **every** venv
that installs this library. Declaring this table is what opts a service in;
without it the plugin does nothing at all. That is deliberate: the fleet-wide
library bump lands in eight services at once, and a plugin that started rewriting
``DATABASE_URL`` on install would break all of them before any had adopted.

Minimal opt-in::

    [tool.tr_testing]
    service = "tr-crm-core"
    migrate_command = ["migrate", "upgrade", "head"]
    migration_globs = ["app/modules/*/alembic/versions/*.py"]

``migration_globs`` is what makes a warm container safe: the container and its
migrated template database are keyed on a hash of those files, so any migration
change mints a new key, hence a new template. A stale schema cannot be reused.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

__all__ = [
    "CONTROL_ENV",
    "ENV_PASSTHROUGH",
    "INFRA_ENV",
    "PLUGIN_OWNED_ENV",
    "POLICY_ENV",
    "TestingConfig",
    "admin_database_url",
    "find_config",
    "passes_scrub",
]

_DEFAULT_POSTGRES_IMAGE = "supabase/postgres:17.6.1.178"
_DEFAULT_REDIS_IMAGE = "redis:7-alpine"

ADMIN_ROLE = "supabase_admin"
APP_ROLE = "postgres"
PASSWORD = "test"
DATABASE_LAYOUT = (
    f"CREATE SCHEMA extensions AUTHORIZATION {APP_ROLE}",
    "CREATE EXTENSION pgcrypto WITH SCHEMA extensions",
    'CREATE EXTENSION "uuid-ossp" WITH SCHEMA extensions',
    "CREATE EXTENSION pg_trgm WITH SCHEMA public",
    "CREATE EXTENSION supabase_vault",
)

ENV_PASSTHROUGH: dict[str, str] = {
    "PATH": "executable lookup for subprocesses (git for G18, the migrate command) and shutil.which",
    "HOME": "~ expansion: the Docker client's ~/.docker config, git config, coverage",
    "USER": "getpass.getuser(), which names pytest's tmp_path base directory",
    "LOGNAME": "getpass.getuser(), which names pytest's tmp_path base directory",
    "TMPDIR": "tempfile (pytest tmp_path, coverage data files)",
    "TMP": "tempfile (pytest tmp_path, coverage data files)",
    "TEMP": "tempfile (pytest tmp_path, coverage data files)",
    "LANG": "locale and text encoding (locale, gettext, subprocess I/O)",
    "LC_*": "locale and text encoding (locale, gettext, subprocess I/O)",
    "TZ": "local-time conversion (libc, tzlocal, dateutil)",
    "TERM": "pytest's terminal writer (colour, width)",
    "CI": "pytest prints full assertion diffs on CI",
    "SSL_CERT_FILE": "TLS trust for httpx, requests and the Docker client",
    "SSL_CERT_DIR": "TLS trust for httpx, requests and the Docker client",
    "REQUESTS_CA_BUNDLE": "TLS trust for httpx, requests and the Docker client",
    "HTTP_PROXY": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "HTTPS_PROXY": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "NO_PROXY": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "ALL_PROXY": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "http_proxy": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "https_proxy": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "no_proxy": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "all_proxy": "stdlib proxy discovery (httpx trust_env) and the Docker client",
    "TEST_DATABASE_URL": "the plugin's CI override (CONTROL_ENV)",
    "TEST_REDIS_URL": "the plugin's CI override (CONTROL_ENV)",
    "PYTHON*": "interpreter settings (PYTHONPATH, PYTHONHASHSEED, PYTHONDONTWRITEBYTECODE)",
    "PYTEST_*": "pytest itself (PYTEST_ADDOPTS, PYTEST_XDIST_WORKER, PYTEST_CURRENT_TEST)",
    "COVERAGE_*": "coverage in xdist workers and subprocesses (COVERAGE_PROCESS_CONFIG, COVERAGE_FILE)",
    "DOCKER_*": "the plugin's Docker client, docker.from_env() (DOCKER_HOST, DOCKER_CONFIG, ...)",
    "XDG_*": "config and cache directories for git (G18) and platformdirs",
    "TR_TESTING_*": "the plugin's own controls (TR_TESTING_RUN_ID, TR_TESTING_FRESH)",
    "GITHUB_ACTIONS": "CI detection (asyncpg, greenlet, google-auth)",
}

INFRA_ENV: tuple[str, ...] = (
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
)

POLICY_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "AUTH_LIB_GATEWAY_SIGNING_SECRET": "test-gateway-signing-secret",
    "AUTH_LIB_SERVICE_TOKEN": "test-outbound-service-token",
    "SERVICE_TOKEN": "test-inbound-service-token",
}

CONTROL_ENV: tuple[str, ...] = (
    "TEST_DATABASE_URL",
    "TEST_REDIS_URL",
    "TR_TESTING_RUN_ID",
    "TR_TESTING_FRESH",
    "PYTEST_XDIST_WORKER",
)

PLUGIN_OWNED_ENV: frozenset[str] = frozenset({*INFRA_ENV, *POLICY_ENV, *CONTROL_ENV})

_PASSTHROUGH_NAMES = frozenset(k for k in ENV_PASSTHROUGH if not k.endswith("*"))
_PASSTHROUGH_PREFIXES = tuple(k[:-1] for k in ENV_PASSTHROUGH if k.endswith("*"))

_STRING_KEYS = ("service", "postgres_image", "redis_image", "database_name")
_LIST_KEYS = ("migrate_command", "migration_globs")
_KNOWN_KEYS = frozenset({*_STRING_KEYS, *_LIST_KEYS, "env"})


def passes_scrub(key: str) -> bool:
    """Whether an inherited environment variable survives the plugin's scrub (case-sensitive)."""
    return key in _PASSTHROUGH_NAMES or key.startswith(_PASSTHROUGH_PREFIXES)


@dataclass(frozen=True)
class TestingConfig:
    """Everything the plugin needs to provision a service's test stack."""

    service: str
    root: Path
    migrate_command: tuple[str, ...]
    migration_globs: tuple[str, ...]
    postgres_image: str = _DEFAULT_POSTGRES_IMAGE
    redis_image: str = _DEFAULT_REDIS_IMAGE
    database_name: str = "test"
    env: tuple[tuple[str, str], ...] = ()
    _fingerprint: list[str] = field(default_factory=list, compare=False, repr=False)

    def fingerprint(self) -> str:
        """Hex digest over the service, its images, the database layout and every migration file.

        Content, not filenames: editing a migration in place (legal while a chain
        is being re-baselined) must invalidate the template, and a filename-only
        hash would not notice.
        """
        if self._fingerprint:
            return self._fingerprint[0]

        digest = hashlib.sha256()
        digest.update(self.service.encode())
        digest.update(self.postgres_image.encode())
        digest.update(self.redis_image.encode())
        for statement in DATABASE_LAYOUT:
            digest.update(statement.encode())
        for path in sorted(self.migration_files()):
            digest.update(str(path.relative_to(self.root)).encode())
            digest.update(path.read_bytes())
        value = digest.hexdigest()
        self._fingerprint.append(value)
        return value

    def migration_files(self) -> list[Path]:
        found: set[Path] = set()
        for pattern in self.migration_globs:
            found.update(p for p in self.root.glob(pattern) if p.is_file())
        return sorted(found)

    @property
    def key(self) -> str:
        """Short fingerprint, used in container and database names."""
        return self.fingerprint()[:12]


def admin_database_url(database_url: str) -> str:
    """The same test database, connected as the image's superuser.

    Tests connect as ``APP_ROLE``, which cannot alter extension-owned objects such as
    ``vault.create_secret``. Fault injection that renames them needs this URL.
    """
    parts = urlsplit(database_url)
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit(parts._replace(netloc=f"{ADMIN_ROLE}:{PASSWORD}@{host}"))


def find_config(start: Path) -> TestingConfig | None:
    """Nearest ``pyproject.toml`` at or above ``start`` declaring ``[tool.tr_testing]``.

    Returns ``None`` when the service has not opted in, which is the common case
    during rollout and must stay completely silent.
    """
    for directory in (start, *start.parents):
        pyproject = directory / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return None
        table = data.get("tool", {}).get("tr_testing")
        if table is None:
            # Keep walking: a service directory inside the monorepo may have its
            # own pyproject without the table while an outer one has it.
            continue
        return _build(table, directory)
    return None


def _build(table: dict[str, object], root: Path) -> TestingConfig:
    unknown = sorted(set(table) - _KNOWN_KEYS)
    if unknown:
        raise pytest.UsageError(f"[tool.tr_testing] has unknown keys: {unknown}")
    if "service" not in table:
        raise pytest.UsageError("[tool.tr_testing] must set service")
    for key in _STRING_KEYS:
        value = table.get(key)
        if key in table and not (isinstance(value, str) and value):
            raise pytest.UsageError(f"[tool.tr_testing] {key} must be a non-empty string")
    for key in _LIST_KEYS:
        value = table.get(key)
        if key in table and not (
            isinstance(value, list) and value and all(isinstance(v, str) and v for v in value)
        ):
            raise pytest.UsageError(
                f"[tool.tr_testing] {key} must be a non-empty list of non-empty strings"
            )

    def _strings(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = table.get(key)
        return tuple(value) if isinstance(value, list) else default

    def _string(key: str, default: str) -> str:
        value = table.get(key)
        return value if isinstance(value, str) else default

    return TestingConfig(
        service=_string("service", ""),
        root=root,
        migrate_command=_strings("migrate_command", ("alembic", "upgrade", "head")),
        migration_globs=_strings("migration_globs", ("**/alembic/versions/*.py",)),
        postgres_image=_string("postgres_image", _DEFAULT_POSTGRES_IMAGE),
        redis_image=_string("redis_image", _DEFAULT_REDIS_IMAGE),
        database_name=_string("database_name", "test"),
        env=_env_table(table.get("env", {})),
    )


def _env_table(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        raise pytest.UsageError("[tool.tr_testing] env must be a table, [tool.tr_testing.env]")
    owned = {k.upper() for k in PLUGIN_OWNED_ENV}
    for key, item in value.items():
        if not isinstance(item, str):
            raise pytest.UsageError(f"[tool.tr_testing.env] {key} must be a string")
        if key.upper() in owned:
            raise pytest.UsageError(
                f"[tool.tr_testing.env] {key} is owned by the plugin and cannot be set here"
            )
    return tuple(value.items())
