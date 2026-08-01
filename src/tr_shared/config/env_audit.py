"""Report .env keys that no settings class claims.

Every service's Settings is extra="ignore", so a renamed or typo'd env key is
discarded without a word. This module names them.

Scope note: one .env feeds many BaseSettings classes (AuthLibSettings with
env_prefix="AUTH_LIB_", WAM's LLMConfig, realty-hub's eight module settings).
The comparison MUST union all reachable classes; comparing against one class
reports live keys as orphans and pushes people into re-declaring fields that
already have an owner.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import AliasChoices, AliasPath
from pydantic_settings import BaseSettings

from tr_shared.logging.setup import get_logger

logger = get_logger(__name__)

_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_env_keys(path: Path | str) -> set[str]:
    """Key names in a dotenv file. Values, comments and blank lines are ignored.

    Never raises: a missing, unreadable (permissions), or non-UTF-8 file all
    resolve to no keys rather than propagating the read error.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {match.group(1) for line in text.splitlines() if (match := _KEY_RE.match(line))}


def _aliases(alias: object) -> set[str]:
    if isinstance(alias, str):
        return {alias}
    if isinstance(alias, AliasChoices):
        return {c for c in alias.choices if isinstance(c, str)}
    if isinstance(alias, AliasPath):
        return {alias.path[0]} if alias.path and isinstance(alias.path[0], str) else set()
    return set()


def _declared_env_keys_by_sensitivity(
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
    mixed (see ``_declared_env_keys_by_sensitivity``) — a public,
    obvious-sounding name here is exactly what previously led an
    ownership-decision caller to re-derive this same false-negative-prone
    merge instead of using ``unclaimed_env_keys``, which keeps the split form
    internally for that reason. Kept for tests exercising the merge itself.
    """
    case_sensitive_declared, case_insensitive_declared = _declared_env_keys_by_sensitivity(*classes)
    return case_sensitive_declared | case_insensitive_declared


def reachable_settings_classes() -> set[type[BaseSettings]]:
    """Every imported BaseSettings subclass, transitively.

    Called at startup, after the app's modules are imported, so module-level
    settings classes (realty-hub) and library ones (AuthLibSettings) are present.
    """
    seen: set[type[BaseSettings]] = set()
    stack = list(BaseSettings.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
    return seen


def unclaimed_env_keys(
    env_file: Path | str = ".env",
    classes: tuple[type[BaseSettings], ...] | None = None,
) -> list[str]:
    """Keys present in ``env_file`` that no settings class declares.

    A key is claimed if ANY owning class would actually bind it: a
    case-sensitive class only via an exact match, a case-insensitive class via
    a case-insensitive match. The two checks are kept separate per class (see
    ``_declared_env_keys_by_sensitivity``) so a case-insensitive match on one
    class can never stand in for a case-sensitive class's exact-match
    requirement.
    """
    owners = classes if classes is not None else tuple(reachable_settings_classes())
    case_sensitive_declared, case_insensitive_declared = _declared_env_keys_by_sensitivity(*owners)
    parsed = parse_env_keys(env_file)
    return sorted(
        key
        for key in parsed
        if key not in case_sensitive_declared and key.upper() not in case_insensitive_declared
    )


def log_unclaimed_env_keys(env_file: Path | str = ".env") -> list[str]:
    """Warn once per unclaimed key. Never raises — a local .env is not a contract.

    A missing file is the normal case (staging/production get config from
    Railway as OS env vars, not a .env) and stays silent. A file that EXISTS
    but cannot be read (permissions) or decoded (not UTF-8) is different: it
    silently defeats this whole audit — the developer sees no warning and
    reasonably assumes their .env is clean, when the truth is the audit never
    ran. That failure mode gets its own warning rather than being folded into
    "found nothing".
    """
    file = Path(env_file)
    if file.exists():
        try:
            file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(
                "env_file_unreadable",
                env_file=str(file),
                error=str(exc),
                hint="Could not read this .env to audit it for unclaimed keys; "
                "treating it as empty rather than failing startup.",
            )
            return []

    unclaimed = unclaimed_env_keys(env_file)
    if unclaimed:
        logger.warning(
            "env_keys_unclaimed",
            env_file=str(env_file),
            keys=unclaimed,
            hint="No settings class declares these — renamed field or typo. "
            "They are silently ignored (extra='ignore').",
        )
    return unclaimed
