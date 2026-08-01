"""Assert every .env.example key has an owner — a settings field, a shell script, or another language's source.

Runs on .env.example, not .env: .env is gitignored and per-developer, so gating
on it fails on machines instead of in CI. Task 7's startup warning covers .env.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_settings import BaseSettings

from tr_shared.config.env_audit import config_owner_classes, unclaimed_env_keys

# Files that can read an env var at runtime in a language that is NOT Python, plus
# the deployment config that injects them. Python is excluded on purpose: a Python
# consumer must declare a settings field, which is the primary check - grepping
# Python source too would exempt every key merely mentioned in a comment and gut
# the guard. Docs and READMEs are excluded for the same reason.
#
# Adding a runtime language to the monorepo means adding its glob here. That is
# enforced by the per-service contract tests rather than by prose: WAM's test goes
# red the moment its Go bot's keys stop being recognised.
_CONSUMER_GLOBS = (
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "Dockerfile*",
    "*.sh",
    "*.go",
)

# Same four names, for the same reasons, as guards.iter_shell_files: .venv holds
# thousands of vendored files that are not ours to police, and .worktrees/.git
# hold COPIES OF THIS SAME REPO at other revisions. Scanning a worktree would let
# a key that only some other branch consumes look claimed on this one - a false
# negative that depends on what a colleague is mid-way through.
#
# Duplicated rather than imported: guards.py keeps this set as a local literal
# inside iter_shell_files, and hoisting it to a shared constant means editing a
# 657-line module eight services depend on, for a change that is not this wave's
# contract. Flagged as a follow-up instead.
_SKIP_DIRS = {".venv", ".worktrees", ".git", "node_modules"}


def _externally_consumed(repo_root: Path, keys: set[str]) -> set[str]:
    """Keys referenced by a whole-word match in non-Python consumer files."""
    if not keys:
        return set()
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(keys)) + r")\b")
    found: set[str] = set()
    for glob in _CONSUMER_GLOBS:
        for path in repo_root.rglob(glob):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            found.update(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return found


def assert_no_orphan_env_keys(
    repo_root: Path,
    *,
    extra_classes: tuple[type[BaseSettings], ...] = (),
) -> None:
    example = repo_root / ".env.example"
    assert example.is_file(), f"{example} is missing — it is the Railway config template"

    owners = tuple(config_owner_classes()) + extra_classes
    unowned = set(unclaimed_env_keys(example, classes=owners))
    orphans = sorted(unowned - _externally_consumed(repo_root, unowned))

    assert not orphans, (
        f".env.example declares keys nothing consumes: {orphans}\n"
        "Every key must be either a field on some BaseSettings class in this "
        "service (env_prefix applied) or referenced by name in a compose file, "
        "Dockerfile, shell script, or non-Python source (e.g. the Go bot). An "
        "orphan here becomes a Railway variable that silently does nothing."
    )
