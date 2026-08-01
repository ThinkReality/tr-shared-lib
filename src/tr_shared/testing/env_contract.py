"""Assert every .env.example key has an owner — a settings field or a shell script.

Runs on .env.example, not .env: .env is gitignored and per-developer, so gating
on it fails on machines instead of in CI. Task 7's startup warning covers .env.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_settings import BaseSettings

from tr_shared.config.env_audit import reachable_settings_classes, unclaimed_env_keys

_SHELL_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml", "Dockerfile*", "*.sh")


def _shell_consumed(repo_root: Path, keys: set[str]) -> set[str]:
    """Keys referenced by a whole-word match in compose/Dockerfile/shell files."""
    if not keys:
        return set()
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(keys)) + r")\b")
    found: set[str] = set()
    for glob in _SHELL_GLOBS:
        for path in repo_root.rglob(glob):
            if any(part in {".venv", "node_modules", ".git"} for part in path.parts):
                continue
            found.update(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return found


def assert_env_example_is_declared(
    repo_root: Path,
    *,
    extra_classes: tuple[type[BaseSettings], ...] = (),
) -> None:
    example = repo_root / ".env.example"
    assert example.is_file(), f"{example} is missing — it is the Railway config template"

    owners = tuple(reachable_settings_classes()) + extra_classes
    unowned = set(unclaimed_env_keys(example, classes=owners))
    orphans = sorted(unowned - _shell_consumed(repo_root, unowned))

    assert not orphans, (
        f".env.example declares keys nothing consumes: {orphans}\n"
        "Every key must be either a field on some BaseSettings class in this "
        "service (env_prefix applied) or referenced by name in a compose file, "
        "Dockerfile or shell script. An orphan here becomes a Railway variable "
        "that silently does nothing."
    )
