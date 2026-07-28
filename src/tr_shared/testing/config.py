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

__all__ = ["TestingConfig", "find_config"]

_DEFAULT_POSTGRES_IMAGE = "postgres:16-alpine"
_DEFAULT_REDIS_IMAGE = "redis:7-alpine"

# pgcrypto (gen_random_uuid), pg_trgm and btree_gin are all NON-TRUSTED
# extensions, so creating them needs a superuser — not merely CREATEDB. The
# container therefore runs as the postgres superuser.
_DEFAULT_EXTENSIONS = ("pgcrypto", "pg_trgm", "btree_gin")


@dataclass(frozen=True)
class TestingConfig:
    """Everything the plugin needs to provision a service's test stack."""

    service: str
    root: Path
    migrate_command: tuple[str, ...]
    migration_globs: tuple[str, ...]
    extensions: tuple[str, ...] = _DEFAULT_EXTENSIONS
    postgres_image: str = _DEFAULT_POSTGRES_IMAGE
    redis_image: str = _DEFAULT_REDIS_IMAGE
    database_name: str = "test"
    _fingerprint: list[str] = field(default_factory=list, compare=False, repr=False)

    def fingerprint(self) -> str:
        """Hex digest over the service, its images, and every migration file.

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


def _build(table: dict[str, object], root: Path) -> TestingConfig | None:
    service = table.get("service")
    if not isinstance(service, str) or not service:
        return None

    def _strings(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = table.get(key)
        if value is None:
            return default
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return tuple(str(v) for v in value)
        return default

    def _string(key: str, default: str) -> str:
        value = table.get(key)
        return value if isinstance(value, str) and value else default

    return TestingConfig(
        service=service,
        root=root,
        migrate_command=_strings("migrate_command", ("alembic", "upgrade", "head")),
        migration_globs=_strings("migration_globs", ("**/alembic/versions/*.py",)),
        extensions=_strings("extensions", _DEFAULT_EXTENSIONS),
        postgres_image=_string("postgres_image", _DEFAULT_POSTGRES_IMAGE),
        redis_image=_string("redis_image", _DEFAULT_REDIS_IMAGE),
        database_name=_string("database_name", "test"),
    )
