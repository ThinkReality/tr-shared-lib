from __future__ import annotations

import re
from pathlib import Path

from pydantic import AliasChoices, AliasPath
from pydantic_settings import BaseSettings

_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_env_keys(path: Path | str) -> set[str]:
    """Key names in a dotenv file. Values, comments and blank lines are ignored.

    A missing, unreadable or non-UTF-8 file raises: a key-set check that reads nothing
    would pass vacuously.
    """
    text = Path(path).read_text(encoding="utf-8")
    return {match.group(1) for line in text.splitlines() if (match := _KEY_RE.match(line))}


def _aliases(alias: object) -> set[str]:
    if isinstance(alias, str):
        return {alias}
    if isinstance(alias, AliasChoices):
        return {c for c in alias.choices if isinstance(c, str)}
    if isinstance(alias, AliasPath):
        return {alias.path[0]} if alias.path and isinstance(alias.path[0], str) else set()
    return set()


def declared_env_keys_by_sensitivity(
    *classes: type[BaseSettings],
) -> tuple[set[str], set[str]]:
    """Every env var name the given classes can consume, split by whether the
    OWNING class requires an exact-case match.

    Returns ``(case_sensitive_declared, case_insensitive_declared)``.
    ``case_sensitive_declared`` entries are kept in their exact declared case
    and must be matched with ``==``. ``case_insensitive_declared`` entries are
    upper-cased and must be matched against a candidate key's upper-cased form.

    Kept as two sets rather than one merged set: a case-sensitive class whose
    field is already SCREAMING_SNAKE_CASE (e.g. ``BaseServiceSettings.
    SERVICE_NAME``, ``case_sensitive=True`` — inherited by every service) has
    a declared name that is indistinguishable, as a bare string, from a
    case-insensitive class's upper-cased declared name. Merging them into one
    set and testing membership with a single ``key.upper() in declared`` check
    lets a wrong-case key match on that coincidence: pydantic-settings would
    never actually bind ``service_name`` to a case-sensitive ``SERVICE_NAME``
    field, but the merged-set check would (wrongly) call it claimed — a false
    negative in the exact guard this module exists to provide.

    Mirrors pydantic-settings' own field-to-env-name resolution
    (``PydanticBaseEnvSettingsSource._extract_field_info`` in
    ``pydantic_settings/sources/base.py``, read against the installed
    pydantic-settings 2.13.1): ``env_prefix`` applies to the bare field-name
    path (subject to ``env_prefix_target``, default ``"variable"``), but to an
    explicit ``validation_alias`` only when the class opts into
    ``env_prefix_target="alias"`` or ``"all"`` — the default target never
    prefixes an alias. When a field has an alias, the bare field name is only
    ALSO a valid env key if the class sets ``populate_by_name`` /
    ``validate_by_name``; otherwise only the alias resolves.
    """
    case_sensitive_declared: set[str] = set()
    case_insensitive_declared: set[str] = set()
    for cls in classes:
        config = cls.model_config
        prefix = config.get("env_prefix", "") or ""
        target = config.get("env_prefix_target", "variable") or "variable"
        case_sensitive = bool(config.get("case_sensitive", False))
        populate_by_name = bool(
            config.get("populate_by_name", False) or config.get("validate_by_name", False)
        )
        bucket = case_sensitive_declared if case_sensitive else case_insensitive_declared
        normalize = (lambda s: s) if case_sensitive else str.upper

        for name, field in cls.model_fields.items():
            alias_names = _aliases(field.validation_alias)
            if alias_names:
                alias_prefix = prefix if target in ("alias", "all") else ""
                bucket.update(normalize(f"{alias_prefix}{alias}") for alias in alias_names)
            if not alias_names or populate_by_name:
                name_prefix = prefix if target in ("variable", "all") else ""
                bucket.add(normalize(f"{name_prefix}{name}"))
    return case_sensitive_declared, case_insensitive_declared


def _declared_env_keys(*classes: type[BaseSettings]) -> set[str]:
    """Every env var name the given settings classes can consume, prefixes
    (and, for a case-sensitive class, exact case) applied.

    Private on purpose: this is the flat, informational view — case-sensitive
    names in their declared case, case-insensitive names upper-cased, unioned
    together. It is NOT safe to test a candidate key's membership in this set
    to decide ownership when case-sensitive and case-insensitive classes are
    mixed (see ``declared_env_keys_by_sensitivity``) — a public,
    obvious-sounding name here is exactly what previously led an
    ownership-decision caller to re-derive this same false-negative-prone
    merge instead of using ``unclaimed_env_keys``, which keeps the split form
    internally for that reason. Kept for tests exercising the merge itself.
    """
    case_sensitive_declared, case_insensitive_declared = declared_env_keys_by_sensitivity(*classes)
    return case_sensitive_declared | case_insensitive_declared
