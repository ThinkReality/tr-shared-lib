"""Structural guards a service runs over its own tree.

Each guard encodes an invariant from ``docs/shared/TR_Testing_Standard.md`` that
nothing in the type system enforces, and whose violation typically surfaces in a
*different* suite than the one that caused it — which is exactly why they survive
code review and need to be executable.

Two rules learned the hard way, both applied throughout:

**Match code, not prose.** An earlier guard scanned every string constant in a
module and reported three innocent files, because
``\"\"\"Tests for CredentialTypeCreate schema.\"\"\"`` lowercases to a string
containing ``"create schema"``. A guard that cries wolf is worse than no guard:
the fix people reach for is an allowlist entry. Every detector here matches AST
structure, and string patterns only inside call arguments.

**An exemption must carry a machine-checkable claim.** Prose alone is how an
exemption outlives the gate that justified it, so ``Exemption`` requires either a
symbol that must still appear in the module or ``must_be_inert``. Reused from
``tenant_header_guard`` rather than reinvented.

Usage, per service, under ``tests/architecture/``::

    from pathlib import Path
    from tr_shared.testing.guards import assert_no_sqlite_dsn

    TESTS = Path(__file__).resolve().parents[1]

    def test_no_sqlite():
        assert_no_sqlite_dsn(TESTS)
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

from tr_shared.testing.tenant_header_guard import Exemption

__all__ = [
    "Exemption",
    "assert_environment_vocabulary",
    "assert_no_auth_chain_bypass",
    "assert_no_env_mutation_in_conftest",
    "assert_no_infra_skips",
    "assert_no_ryuk_disabled",
    "assert_no_schema_construction",
    "assert_no_sqlite_dsn",
    "assert_no_testing_flag_in_production",
    "find_violations",
    "iter_shell_files",
]

Detector = Callable[[str], list[int]]


# --------------------------------------------------------------------------- #
# Shared machinery
# --------------------------------------------------------------------------- #


def iter_python_files(root: Path, *, skip: tuple[str, ...] = ()) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        if any(part in skip for part in path.parts):
            continue
        yield path


def iter_shell_files(root: Path, *, skip: tuple[str, ...] = ()) -> Iterator[Path]:
    """Shell scripts under ``root``.

    ``.venv`` holds thousands of vendored scripts that are not ours to police.
    ``.worktrees`` and ``.git`` hold *copies of this same repo* checked out at other
    revisions — a guard that scans them reports the same violation two or three times
    and, worse, goes red because of a branch someone else is mid-way through. All three
    are skipped unconditionally rather than left to each caller to remember.
    """
    ignored = {".venv", ".worktrees", ".git", "node_modules"}
    for path in sorted(root.rglob("*.sh")):
        if any(part in skip or part in ignored for part in path.parts):
            continue
        yield path


def find_violations(
    root: Path,
    detector: Detector,
    *,
    skip: tuple[str, ...] = (),
    exclude: tuple[Path, ...] = (),
    iterator: Callable[..., Iterator[Path]] = iter_python_files,
) -> dict[str, list[int]]:
    """Map of ``root``-relative path -> offending line numbers.

    ``iterator`` selects which files a guard sees. It defaults to Python because
    every guard but one is an AST scan; the environment-vocabulary guard passes
    ``iter_shell_files``. This is a parameter rather than a second copy of the
    walk-parse-collect loop on purpose — the standard's §1.8 forbids growing a
    second guard framework, and the ``Exemption`` staleness checks below are the
    part worth reusing.
    """
    found: dict[str, list[int]] = {}
    resolved_excludes = {p.resolve() for p in exclude}
    for path in iterator(root, skip=skip):
        if path.resolve() in resolved_excludes:
            continue
        try:
            # utf-8-sig: a BOM makes ast.parse raise on line 1, and a crashing
            # scan is a silently absent guard. One module in the fleet has one.
            source = path.read_text(encoding="utf-8-sig")
        except OSError:  # pragma: no cover - unreadable file
            continue
        try:
            hits = detector(source)
        except SyntaxError:  # pragma: no cover - not our file to fix
            continue
        if hits:
            found[str(path.relative_to(root))] = hits
    return found


def _assert(
    root: Path,
    detector: Detector,
    allowlist: Mapping[str, Exemption],
    message: str,
    *,
    skip: tuple[str, ...] = (),
    exclude: tuple[Path, ...] = (),
    iterator: Callable[..., Iterator[Path]] = iter_python_files,
) -> None:
    found = find_violations(root, detector, skip=skip, exclude=exclude, iterator=iterator)

    undocumented = {m: lines for m, lines in found.items() if m not in allowlist}
    assert not undocumented, f"{message}\n{undocumented}"

    stale = set(allowlist) - set(found)
    assert not stale, (
        f"Allowlisted modules that no longer violate this guard: {sorted(stale)}. "
        "Remove them, or the allowlist starts covering code nobody checked."
    )

    for module, exemption in allowlist.items():
        assert exemption.requires_symbols or exemption.must_be_inert, (
            f"{module}: exemption rests on prose alone. Name a gating symbol in "
            "requires_symbols, or set must_be_inert=True."
        )
        source = (root / module).read_text(encoding="utf-8-sig")
        for symbol in exemption.requires_symbols:
            assert symbol in source, (
                f"{module} is exempt because of {symbol!r}, which is no longer in "
                "the module. The reason it was safe is gone — re-verify it or "
                "remove the violation."
            )


def _string_args(node: ast.Call) -> Iterator[tuple[str, int]]:
    """Every string literal passed to this call, with the call's line number."""
    for arg in ast.walk(node):
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield arg.value, node.lineno


def _assignment_targets(node: ast.AST) -> Iterator[ast.expr]:
    if isinstance(node, ast.Assign):
        yield from node.targets
    elif isinstance(node, ast.AnnAssign):
        yield node.target


# --------------------------------------------------------------------------- #
# G2 — no sqlite
# --------------------------------------------------------------------------- #

_SQLITE = re.compile(r"sqlite(\+\w+)?:", re.IGNORECASE)


def detect_sqlite_dsn(source: str) -> list[int]:
    """Any sqlite DSN, wherever it appears as a value."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _SQLITE.search(node.value):
                hits.append(node.lineno)
    return sorted(set(hits))


def assert_no_sqlite_dsn(
    tests_root: Path, allowlist: Mapping[str, Exemption] | None = None
) -> None:
    """G2. Postgres semantics are part of what is under test.

    Schemas, JSONB, partial indexes, ``date_trunc`` and FK behaviour do not exist
    or differ on sqlite, so a suite that passes there and fails on Postgres is
    worse than no suite. Both sqlite fixtures found in the fleet were also dead
    code that every test file shadowed — the engine nobody noticed was wrong.
    """
    _assert(
        tests_root,
        detect_sqlite_dsn,
        allowlist or {},
        "sqlite DSN under tests/. PG semantics are part of what is being tested; "
        "use the integration lane's real Postgres.",
    )


# --------------------------------------------------------------------------- #
# G5 — the auth chain may not be disabled
# --------------------------------------------------------------------------- #

_AUTH_DEPENDENCIES = {"require_auth", "optional_auth", "get_gateway_identity"}
_AUTH_MIDDLEWARE = {"GatewayHMACMiddleware", "IdentityExtractionMiddleware"}


def detect_auth_chain_bypass(source: str) -> list[int]:
    """Overrides, patches and env flags that switch authentication off.

    ``dependency_overrides[require_auth]`` is named explicitly. An earlier
    version of this guard forbade "disabling, patching or subclass-overriding"
    the middleware, which is literally none of those things — so it passed green
    on 28 files that were doing exactly what it existed to prevent.
    """
    hits: list[int] = []
    tree = ast.parse(source)

    for node in ast.walk(tree):
        # app.dependency_overrides[require_auth] = ...
        if isinstance(node, ast.Subscript):
            target = node.value
            if isinstance(target, ast.Attribute) and target.attr == "dependency_overrides":
                key = node.slice
                if isinstance(key, ast.Name) and key.id in _AUTH_DEPENDENCIES:
                    hits.append(node.lineno)
                elif isinstance(key, ast.Attribute) and key.attr in _AUTH_DEPENDENCIES:
                    hits.append(node.lineno)

        # GatewayHMACMiddleware.dispatch = _passthrough
        for target in _assignment_targets(node):
            if isinstance(target, ast.Attribute):
                base = target.value
                if isinstance(base, ast.Name) and base.id in _AUTH_MIDDLEWARE:
                    hits.append(target.lineno)

        if isinstance(node, ast.Call):
            func = node.func
            # monkeypatch.setattr(GatewayHMACMiddleware, "dispatch", ...)
            if isinstance(func, ast.Attribute) and func.attr in {"setattr", "object"}:
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id in _AUTH_MIDDLEWARE:
                        hits.append(node.lineno)
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value in _AUTH_MIDDLEWARE:
                            hits.append(node.lineno)
            # patch("...GatewayHMACMiddleware.dispatch")
            for value, lineno in _string_args(node):
                if any(name in value for name in _AUTH_MIDDLEWARE):
                    hits.append(lineno)
                if "DEV_MODE_BYPASS" in value:
                    hits.append(lineno)

        # os.environ["AUTH_LIB_DEV_MODE_BYPASS"] = "true"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "DEV_MODE_BYPASS" in node.value:
                hits.append(node.lineno)

    return sorted(set(hits))


def assert_no_auth_chain_bypass(
    tests_root: Path, allowlist: Mapping[str, Exemption] | None = None
) -> None:
    """G5. Vary the persona, never the middleware.

    ``AUTH_LIB_DEV_MODE_BYPASS`` short-circuits HMAC verification *and*
    ``require_auth``, and a ``dependency_overrides[require_auth]`` is never even
    reached because the middleware rejects the request first — which is why 28
    media tests returned 403 while their authors believed auth was stubbed.
    Use ``shared_auth_lib.testing.signed_client`` instead: every real layer runs,
    and only the out-of-process AuthContext lookup is substituted.
    """
    _assert(
        tests_root,
        detect_auth_chain_bypass,
        allowlist or {},
        "The auth chain is being disabled rather than satisfied. Use "
        "shared_auth_lib.testing.signed_client(app, persona) and vary the persona.",
    )


# --------------------------------------------------------------------------- #
# G7 — schema comes from migrations
# --------------------------------------------------------------------------- #

_SCHEMA_DDL = re.compile(r"\b(drop|create)\s+schema\b", re.IGNORECASE)
_MIGRATION_API = {"upgrade", "downgrade"}


def detect_schema_construction(source: str) -> list[int]:
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            for value, lineno in _string_args(node):
                if _SCHEMA_DDL.search(value):
                    hits.append(lineno)
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr == "create_all":
                    hits.append(node.lineno)
                # alembic's command.upgrade(cfg, "head") — text matching cannot
                # see this, because "upgrade head" never appears in the source.
                elif (
                    func.attr in _MIGRATION_API
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "command"
                ):
                    hits.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "create_all":
            # conn.run_sync(Base.metadata.create_all) — passed, not called
            hits.append(node.lineno)
    return sorted(set(hits))


def assert_no_schema_construction(
    root: Path,
    allowlist: Mapping[str, Exemption] | None = None,
    *,
    exclude: tuple[Path, ...] = (),
) -> None:
    """G7. One owner builds the schema, from migrations.

    ``create_all`` cannot produce Postgres schemas, raw-SQL migration effects, or
    the ``alembic_version`` rows the round-trip suites assert on, and it hides
    metadata-only bugs that migrations catch. Worse, a suite that rebuilds the
    database mid-session leaves every suite that ran before it on residue from
    the previous run: tr-crm-core reported 119 failures from a cold database and
    48 from a warm one, unchanged, for months.
    """
    _assert(
        root,
        detect_schema_construction,
        allowlist or {},
        "Schema construction outside the single owner. Build nothing here — the "
        "integration lane's template is already migrated before your first test.",
        exclude=exclude,
    )


# --------------------------------------------------------------------------- #
# G9 — conftests do not rewrite the environment
# --------------------------------------------------------------------------- #

_ENV_OWNED = {
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
}


def detect_env_mutation(source: str) -> list[int]:
    """Assignment into ``os.environ`` for a variable the plugin owns.

    ``setdefault`` is caught too: it is what a developer's exported shell
    variable defeats, which is the realistic path to a test run pointed at a
    remote database.
    """
    hits: list[int] = []
    tree = ast.parse(source)

    for node in ast.walk(tree):
        for target in _assignment_targets(node):
            if not isinstance(target, ast.Subscript):
                continue
            base = target.value
            is_environ = (isinstance(base, ast.Attribute) and base.attr == "environ") or (
                isinstance(base, ast.Name) and base.id == "environ"
            )
            key = target.slice
            if (
                is_environ
                and isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value in _ENV_OWNED
            ):
                hits.append(target.lineno)

        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "setdefault"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in _ENV_OWNED
            ):
                hits.append(node.lineno)

    return sorted(set(hits))


def assert_no_env_mutation_in_conftest(
    tests_root: Path, allowlist: Mapping[str, Exemption] | None = None
) -> None:
    """G9. The plugin owns the infrastructure variables.

    Scoped to conftests, because that is where a value set at import time wins
    the race against the app's engine construction. The migration round-trip
    fixtures legitimately retarget ``DATABASE_URL`` mid-session and belong in the
    allowlist with ``requires_symbols=("_roundtrip",)``.
    """
    found_conftests = {str(p.relative_to(tests_root)): p for p in tests_root.rglob("conftest.py")}
    violations = {}
    for rel, path in found_conftests.items():
        hits = detect_env_mutation(path.read_text(encoding="utf-8-sig"))
        if hits:
            violations[rel] = hits

    allow = allowlist or {}
    undocumented = {m: v for m, v in violations.items() if m not in allow}
    assert not undocumented, (
        "A conftest is rewriting infrastructure environment variables the test "
        "plugin owns. Setting them here re-introduces the divergence where two "
        f"suites in one process talk to two different databases:\n{undocumented}"
    )
    stale = set(allow) - set(violations)
    assert not stale, f"Stale G9 exemptions: {sorted(stale)}"


# --------------------------------------------------------------------------- #
# G10 / G11 / G12
# --------------------------------------------------------------------------- #


def detect_ryuk_disabled(source: str) -> list[int]:
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "TESTCONTAINERS_RYUK_DISABLED" in node.value:
                hits.append(node.lineno)
    return sorted(set(hits))


def assert_no_ryuk_disabled(
    tests_root: Path, allowlist: Mapping[str, Exemption] | None = None
) -> None:
    """G10. Disabling the reaper leaks containers for everyone.

    The variable is process-global, so one conftest setting it switches cleanup
    off for the entire run — and cleanup then depends on a ``with`` block that
    does not execute on ``-x``, Ctrl-C or a crash. Four Postgres containers were
    found running nine days after the fact, 156 MiB each.
    """
    _assert(
        tests_root,
        detect_ryuk_disabled,
        allowlist or {},
        "TESTCONTAINERS_RYUK_DISABLED is process-global: it disables container "
        "cleanup for the whole run, not just this fixture.",
    )


def detect_infra_skip(source: str) -> list[int]:
    """``pytest.skip`` whose reason mentions infrastructure being unavailable."""
    signals = (
        "not reachable",
        "unavailable",
        "not available",
        "docker",
        "postgres",
        "redis",
        "infra",
    )
    hits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_skip = (isinstance(func, ast.Attribute) and func.attr == "skip") or (
            isinstance(func, ast.Name) and func.id == "skip"
        )
        if not is_skip:
            continue
        for value, lineno in _string_args(node):
            lowered = value.lower()
            if any(signal in lowered for signal in signals):
                hits.append(lineno)
    return sorted(set(hits))


def assert_no_infra_skips(
    tests_root: Path, allowlist: Mapping[str, Exemption] | None = None
) -> None:
    """G11. Missing infrastructure is a failure, not a skip.

    A suite that skips itself when its database is absent reports success for
    tests that never ran — and one service's API harness did exactly that,
    green-skipping its entire API suite whenever Redis was down.
    """
    _assert(
        tests_root,
        detect_infra_skip,
        allowlist or {},
        "Skipping because infrastructure is missing turns an outage into a green "
        "run. Let it fail; the integration lane provisions what it needs.",
    )


_TEST_FLAGS = {"TESTING", "PYTEST_CURRENT_TEST", "IS_TEST", "UNDER_TEST"}


def detect_testing_flag(source: str) -> list[int]:
    """Production code reading a "am I under test?" flag."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in _TEST_FLAGS:
            hits.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in _TEST_FLAGS:
                hits.append(node.lineno)
    return sorted(set(hits))


def assert_no_testing_flag_in_production(
    app_root: Path, allowlist: Mapping[str, Exemption] | None = None
) -> None:
    """G12. Production code must not know it is under test.

    Such a flag only ever exists because a real dependency was unavailable in
    tests — one service disabled rate limiting through it, so the limiter it
    shipped was never the limiter it tested. The integration lane supplies a real
    Redis, which removes the reason.
    """
    _assert(
        app_root,
        detect_testing_flag,
        allowlist or {},
        "Production code is branching on being under test. The integration lane "
        "provides the real dependency; delete the flag and test the real path.",
        skip=("alembic",),
    )


# --------------------------------------------------------------------------- #
# G13 — environment vocabulary in shell
# --------------------------------------------------------------------------- #

#: The only four values ``ENVIRONMENT`` may take. Defined once in
#: ``tr_shared.contracts.Environment``; repeated here as plain strings because this
#: guard reads shell text, not Python, and importing the enum would not help it.
_CANONICAL_ENVIRONMENTS = frozenset({"development", "test", "staging", "production"})

#: ``$ENVIRONMENT`` or ``${ENVIRONMENT}`` compared against a literal, either operand
#: order, with ``=``/``==``/``!=``.
#:
#: Deliberately NOT anchored on the variable being immediately followed by the operator:
#: shell writes ``[ "$ENVIRONMENT" = "dev" ]``, where a quote and a space intervene. The
#: gateway-local guard this replaces required ``ENVIRONMENT==``/``!=`` with nothing
#: between, so it matched Python and was structurally blind to every shell script in the
#: fleet — it reported clean while five real violations sat in the files it scanned.
#:
#: **Whitespace around the operator is mandatory**, and that is what separates a
#: comparison from an assignment. ``ENVIRONMENT="${ENVIRONMENT:-production}"`` is a
#: default assignment appearing in seven scripts; without ``\s+`` the reverse-operand
#: branch reads its left-hand side as the literal ``ENVIRONMENT``, flags it as
#: non-canonical, and the guard fires on all eight services instead of the two that are
#: actually wrong. POSIX ``test`` requires the spaces, so demanding them costs nothing.
_ENV_COMPARISON = re.compile(
    r"""(?:
          \$\{?ENVIRONMENT\}? ["']? \s+ (?:==|!=|=) \s+ ["']?(?P<rhs>[A-Za-z_][\w-]*)
        | ["']?(?P<lhs>[A-Za-z_][\w-]*)["']? \s+ (?:==|!=|=) \s+ ["']?\$\{?ENVIRONMENT\}?
        )""",
    re.VERBOSE,
)

#: ``case "$ENVIRONMENT" in`` — the patterns follow on later lines, so the block is
#: tracked across lines rather than matched in one go.
_ENV_CASE_OPEN = re.compile(r"""case\s+["']?\$\{?ENVIRONMENT\}?["']?\s+in""")
_CASE_PATTERN = re.compile(r"""^\s*\(?\s*(?P<pats>[A-Za-z_|\s*?\[\]-]+?)\s*\)""")


def detect_environment_vocabulary(source: str) -> list[int]:
    """Shell comparing ``$ENVIRONMENT`` against a non-canonical literal.

    Encodes the **rule** — anything outside the canonical four — rather than a list
    of the spellings a past audit happened to find. A guard built from the instance
    list catches ``dev`` and waves through ``qa``, ``Production`` and ``uat``; the
    recorded lesson is `guard-the-invariant-not-the-instance-list`.

    Not flagged: ``ENVIRONMENT="${ENVIRONMENT:-production}"``, which appears in seven of
    the eight services. It is a default assignment, and assignments have no whitespace
    around ``=`` while ``test`` comparisons must — see ``_ENV_COMPARISON``. An earlier
    draft of this guard flagged all seven.
    """
    hits: list[int] = []
    in_case = False
    for number, line in enumerate(source.splitlines(), 1):
        code = line.split("#", 1)[0]
        if not code.strip():
            continue

        if _ENV_CASE_OPEN.search(code):
            in_case = True
            continue
        if in_case:
            if "esac" in code:
                in_case = False
            elif (match := _CASE_PATTERN.match(code)) is not None:
                patterns = (p.strip() for p in match.group("pats").split("|"))
                if any(p and p != "*" and p not in _CANONICAL_ENVIRONMENTS for p in patterns):
                    hits.append(number)
            continue

        for match in _ENV_COMPARISON.finditer(code):
            literal = match.group("rhs") or match.group("lhs")
            if literal and literal not in _CANONICAL_ENVIRONMENTS:
                hits.append(number)
    return sorted(set(hits))


def assert_environment_vocabulary(
    service_root: Path, allowlist: Mapping[str, Exemption] | None = None
) -> None:
    """G13. Shell scripts may only compare ``$ENVIRONMENT`` against the canonical four.

    ``ENVIRONMENT`` takes exactly ``development | test | staging | production``.
    ``BaseServiceSettings`` types the field to ``tr_shared.contracts.Environment``, so
    Python rejects anything else at startup — but shell scripts run *before* Python and
    were never covered. Two services still accepted ``dev`` and ``local``, and, more
    importantly, **omitted ``test``**: a container running ``ENVIRONMENT=test`` took the
    production branch and skipped migrations.

    Accepting a retired spelling is also the dual-format acceptance the development-phase
    directive bans outright. The canonical form is::

        if [ "$ENVIRONMENT" = "development" ] || [ "$ENVIRONMENT" = "test" ]; then

    Point this at the **service root**, not ``tests/`` — ``deploy.sh`` and
    ``docker-entrypoint.sh`` live at the top level, which is exactly why the task lists
    of an earlier programme (scoped to ``app/`` and ``tests/``) never touched them.
    """
    _assert(
        service_root,
        detect_environment_vocabulary,
        allowlist or {},
        "Shell script compares $ENVIRONMENT against a value outside "
        "{development, test, staging, production}. Do not add the spelling as an "
        "alias — that is the shim the directive forbids. Note that omitting 'test' "
        "silently routes test containers down the production branch.",
        iterator=iter_shell_files,
    )
