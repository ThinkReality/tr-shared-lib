"""Assert every .env.example key has an owner — a settings field, a shell script, or another language's source."""

from __future__ import annotations

import ast
import importlib
import re
import types
import typing
from pathlib import Path
from typing import Any

from pydantic import Json
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, EnvSettingsSource, NoDecode

from tr_shared.config.env_audit import declared_env_keys_by_sensitivity, parse_env_keys
from tr_shared.testing.config import ENV_PASSTHROUGH, find_config
from tr_shared.testing.guards import IGNORED_DIRS

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

_SETTINGS_BASES = frozenset({"BaseSettings", "BaseServiceSettings", "AuthLibSettings"})


def _externally_consumed(repo_root: Path, keys: set[str]) -> set[str]:
    """Keys referenced by a whole-word match in non-Python consumer files."""
    if not keys:
        return set()
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(keys)) + r")\b")
    found: set[str] = set()
    for glob in _CONSUMER_GLOBS:
        for path in repo_root.rglob(glob):
            if any(part in IGNORED_DIRS for part in path.relative_to(repo_root).parts):
                continue
            found.update(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return found


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return None


def _module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _settings_class_names_by_module(root: Path) -> dict[Path, list[str]]:
    candidates: dict[Path, dict[str, set[str]]] = {}
    paths = [
        p for p in sorted(root.rglob("*.py")) if not set(p.relative_to(root).parts) & IGNORED_DIRS
    ]
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        classes = {
            node.name: {name for b in node.bases if (name := _base_name(b))}
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        if classes:
            candidates[path] = classes

    settings_names = set(_SETTINGS_BASES)
    changed = True
    while changed:
        changed = False
        for classes in candidates.values():
            for name, bases in classes.items():
                if name not in settings_names and bases & settings_names:
                    settings_names.add(name)
                    changed = True

    by_module: dict[Path, list[str]] = {}
    for path, classes in candidates.items():
        names = [n for n, bases in classes.items() if bases & settings_names]
        if names:
            by_module[path] = names
    return by_module


def settings_class_names(root: Path) -> set[str]:
    """Names of the settings classes ``settings_classes`` would return, found by AST only."""
    return {name for names in _settings_class_names_by_module(root).values() for name in names}


def settings_classes(root: Path) -> list[type[BaseSettings]]:
    """Every settings class defined under ``root``, inherited fields included.

    Modules are AST-scanned first; only those defining a top-level class whose bases
    resolve by name to a settings class (``BaseSettings``, ``BaseServiceSettings``,
    ``AuthLibSettings``, or another such class under ``root``) are imported. ``root``'s
    parent must be importable. Zero classes fails the caller.
    """
    found: list[type[BaseSettings]] = []
    for path, names in _settings_class_names_by_module(root).items():
        module = importlib.import_module(_module_name(path, root))
        for name in names:
            obj = getattr(module, name, None)
            if isinstance(obj, type) and issubclass(obj, BaseSettings):
                found.append(obj)
    assert found, f"found zero settings classes under {root}"
    return sorted(found, key=lambda c: (c.__module__, c.__qualname__))


def _unclaimed(keys: set[str], owners: tuple[type[BaseSettings], ...]) -> list[str]:
    case_sensitive, case_insensitive = declared_env_keys_by_sensitivity(*owners)
    return sorted(k for k in keys if k not in case_sensitive and k.upper() not in case_insensitive)


def unclaimed_env_keys(path: Path | str, classes: tuple[type[BaseSettings], ...]) -> list[str]:
    """Keys in the dotenv file at ``path`` that none of ``classes`` would bind.

    A case-sensitive class claims a key only by exact match, a case-insensitive one
    by a case-insensitive match; the two are kept apart so one never stands in for
    the other.
    """
    return _unclaimed(parse_env_keys(path), classes)


def assert_no_orphan_env_keys(
    repo_root: Path,
    *,
    extra_classes: tuple[type[BaseSettings], ...] = (),
) -> None:
    """G15. Every ``.env.example`` and ``[tool.tr_testing.env]`` key has an owner.

    Owners are the settings classes under ``repo_root / "app"`` plus ``extra_classes``.
    A ``.env.example`` key may also be owned by a non-Python consumer; a table key only
    by a settings class.
    """
    example = repo_root / ".env.example"
    assert example.is_file(), f"{example} is missing — it is the Railway config template"

    owners = tuple(settings_classes(repo_root / "app")) + extra_classes
    unowned = set(unclaimed_env_keys(example, classes=owners))
    orphans = sorted(unowned - _externally_consumed(repo_root, unowned))

    assert not orphans, (
        f".env.example declares keys nothing consumes: {orphans}\n"
        "Every key must be either a field on some BaseSettings class in this "
        "service (env_prefix applied) or referenced by name in a compose file, "
        "Dockerfile, shell script, or non-Python source (e.g. the Go bot). An "
        "orphan here becomes a Railway variable that silently does nothing."
    )

    config = find_config(repo_root)
    table_keys = {key for key, _ in config.env} if config is not None else set()
    table_orphans = _unclaimed(table_keys, owners)
    assert not table_orphans, (
        f"[tool.tr_testing.env] sets keys no settings class reads: {table_orphans}"
    )


_LINE = re.compile(r"^(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_SINGLE_QUOTED = re.compile(r"^'[^']*'$")
_DOUBLE_QUOTED = re.compile(r'^"[^"$\\`]*"$')
_UNQUOTED = re.compile(r"^[^\s'\"$\\`]*$")


_INLINE_COMMENT = re.compile(r" +#.*")
_TAB_BEFORE_HASH = re.compile(r"[ \t]*\t[ \t]*#")
_QUOTED = re.compile(r"(['\"]).*\1")


def _without_comment(value: str) -> str:
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        if end != -1 and _INLINE_COMMENT.fullmatch(value[end + 1 :]):
            return value[: end + 1]
        return value
    return _INLINE_COMMENT.split(value, maxsplit=1)[0]


def _portability_problem(value: str) -> str | None:
    value = _without_comment(value)
    if not _QUOTED.fullmatch(value) and _TAB_BEFORE_HASH.search(value):
        return "use a space before #"
    inner = (
        value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" else value
    )
    if inner.startswith(("[", "{")):
        return "JSON value (use a comma-separated list)"
    if _SINGLE_QUOTED.match(value) or _DOUBLE_QUOTED.match(value) or _UNQUOTED.match(value):
        return None
    return "quote a value with a space, single-quote a value with $"


def assert_env_example_is_portable(repo_root: Path) -> None:
    """G19. Every ``.env.example`` value reads the same in uv, compose and python-dotenv."""
    path = repo_root / ".env.example"
    assert path.is_file(), f"{path} is missing"
    problems: list[str] = []
    seen: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            problems.append(f"{number}: not KEY=value")
            continue
        key, value = match.groups()
        if key in seen:
            problems.append(f"{number}: {key} repeats an earlier key")
        seen.add(key)
        problem = _portability_problem(value)
        if problem:
            problems.append(f"{number}: {key}: {problem}")
    assert not problems, f"{path} is not portable across .env parsers:\n" + "\n".join(problems)


def _union_members(annotation: object) -> tuple[Any, ...]:
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return tuple(a for a in typing.get_args(annotation) if a is not type(None))
    return ()


def _is_json(field: FieldInfo) -> bool:
    return any(m is Json or type(m) is Json for m in field.metadata)


def _json_decoded(source: EnvSettingsSource, field: FieldInfo) -> bool:
    members = _union_members(field.annotation)
    if members:
        return any(
            _is_json(member) or source.field_is_complex(member)
            for member in (FieldInfo.from_annotation(m) for m in members)
        )
    if _is_json(field):
        return True
    return source.field_is_complex(field) and NoDecode not in field.metadata


def _shadowed(env_name: str) -> bool:
    name = env_name.upper()
    for entry in ENV_PASSTHROUGH:
        if entry.endswith("*"):
            if name.startswith(entry[:-1].upper()):
                return True
        elif name == entry.upper():
            return True
    return False


def assert_settings_are_env_safe(repo_root: Path, *, package: str = "app") -> None:
    """G21. No settings field is JSON-decoded from the environment or shadowed by the scrub allowlist.

    (a) A field pydantic-settings would JSON-decode fails unless its own metadata holds
    ``NoDecode`` (``CsvList``); a union fails when any member is complex. (b) A field
    whose env name an ``ENV_PASSTHROUGH`` entry matches fails, prefixes and aliases applied.
    Settings classes are found under ``repo_root / package``: ``app`` in a service, the
    package path in a library.
    """
    problems: list[str] = []
    for cls in settings_classes(repo_root / package):
        source = EnvSettingsSource(cls)
        label = f"{cls.__module__}.{cls.__qualname__}"
        for name, field in cls.model_fields.items():
            if _json_decoded(source, field):
                problems.append(f"{label}.{name}: JSON-decoded from the environment; use CsvList")
        case_sensitive, case_insensitive = declared_env_keys_by_sensitivity(cls)
        for env_name in sorted(case_sensitive | case_insensitive):
            if _shadowed(env_name):
                problems.append(f"{label}: {env_name} is passed through by the test scrub")
    assert not problems, "Settings are not env-safe:\n" + "\n".join(problems)
