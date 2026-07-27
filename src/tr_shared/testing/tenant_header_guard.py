"""Fleet guard: the raw ``X-Tenant-ID`` header is identity CONTEXT, not authorization.

The gateway emits a signed ``X-Tenant-ID`` on the JWT path. That is safe only
while every downstream service keeps authorizing on ``AuthContext.tenant_id``
resolved from crm-core, and treats a raw header read as something that must
first be HMAC-verified or service-token gated.

The reason this lives in the shared library rather than in one service's test
suite: the invariant is fleet-wide, but the code that can break it is in eight
separate repositories. A guard that only scans one of them is a guard against
one eighth of the risk — and the CLASS 5-a exploit it exists to prevent
(a public route propagating a client-supplied ``X-Tenant-ID``, the gateway
HMAC-signing it, downstream reading the signature as proof of provenance) was
found in the gateway and exploited through lead-management, neither of which was
covered by the crm-core copy of this check.

Usage, per service, in ``tests/architecture/test_raw_tenant_header_guard.py``::

    from pathlib import Path
    from tr_shared.testing import Exemption, assert_no_undocumented_raw_tenant_header_reads

    APP_ROOT = Path(__file__).resolve().parents[2] / "app"
    ALLOWLIST = {
        "api/v1/endpoints/ingestion/webhooks.py": Exemption(
            reason="...what authenticates the caller BEFORE the header is trusted...",
            requires_symbols=("validate_service_token",),
        ),
    }

    def test_no_undocumented_raw_tenant_header_reads():
        assert_no_undocumented_raw_tenant_header_reads(APP_ROOT, ALLOWLIST)

An exemption must carry a machine-checkable claim — a gating symbol that must
still appear in the module, or ``must_be_inert``. Prose alone is how an
exemption outlives the gate that justified it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Exemption",
    "assert_exemptions_are_machine_verified",
    "assert_no_stale_exemptions",
    "assert_no_undocumented_raw_tenant_header_reads",
    "find_raw_tenant_header_readers",
    "iter_app_modules",
    "scan_source_for_raw_tenant_header_reads",
]

# The tenant header, by every spelling a reader could use.
_TENANT_HEADER_LITERALS = {"x-tenant-id"}
_TENANT_HEADER_ATTRS = {"TENANT_ID"}

# String methods that normalise a header key without changing which header it is.
_KEY_NORMALISERS = {"lower", "upper", "strip", "casefold"}

# Import roots that would let a raw, unverified tenant value reach data.
_NON_INERT_IMPORT_MARKERS = ("repositories", "services", "get_db", "AsyncSession")

_MIN_REASON_LENGTH = 60


@dataclass(frozen=True)
class Exemption:
    """A permitted raw-header read, plus the proof that makes it permitted."""

    reason: str
    # Symbols that MUST appear in the module: the gate the reason claims exists.
    requires_symbols: tuple[str, ...] = ()
    # The value must reach nothing: no repository, service or DB session import.
    must_be_inert: bool = False
    # Extra import markers treated as "this module is not inert", per service.
    extra_non_inert_markers: tuple[str, ...] = field(default=())


def iter_app_modules(app_root: Path) -> Iterator[Path]:
    """Every first-party module under ``app_root``, skipping migrations."""
    for path in sorted(app_root.rglob("*.py")):
        if "alembic" in path.parts or path.name == "__init__.py":
            continue
        yield path


def _is_tenant_header_key(node: ast.AST, aliases: set[str] | None = None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.lower() in _TENANT_HEADER_LITERALS
    # Case/whitespace normalisation on the key: HttpHeader.TENANT_ID.value.lower().
    # This is not a contrived form — ASGI lowercases header names, so normalising
    # before the lookup is the *correct* thing to write, and lead-management does
    # exactly that. An earlier version of this matcher stopped at `.value` and
    # reported that service as having zero raw reads.
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in _KEY_NORMALISERS:
            return _is_tenant_header_key(node.func.value, aliases)
    # HttpHeader.TENANT_ID.value / GatewayHeaders.TENANT_ID
    if isinstance(node, ast.Attribute):
        if node.attr in _TENANT_HEADER_ATTRS:
            return True
        if node.attr == "value" and isinstance(node.value, ast.Attribute):
            return node.value.attr in _TENANT_HEADER_ATTRS
    # A module/local constant bound to the header name: TENANT_HEADER = "x-tenant-id"
    if isinstance(node, ast.Name) and aliases:
        return node.id in aliases
    return False


def _header_name_aliases(tree: ast.AST) -> set[str]:
    """Names bound to the tenant header string anywhere in the module.

    Without this, ``KEY = "x-tenant-id"`` followed by ``headers.get(KEY)`` reads
    the header while presenting no literal for the matcher to see.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_tenant_header_key(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if _is_tenant_header_key(node.value) and isinstance(node.target, ast.Name):
                aliases.add(node.target.id)
    return aliases


def _is_headers_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "headers":
        return True
    # dict(request.headers) / MutableHeaders(request.headers) / ...
    if isinstance(node, ast.Call):
        return any(_is_headers_expr(arg) for arg in node.args)
    return False


def _headers_aliases(tree: ast.AST) -> set[str]:
    """Names bound to a ``.headers`` mapping.

    ``headers = request.headers`` then ``headers.get("x-tenant-id")`` is an
    ordinary refactor, not a contrived evasion — but it detaches the read from
    the ``.headers`` attribute the matcher keys on, so it must be tracked.

    Function PARAMETERS count too. Extracting the resolution into
    ``_resolve_tenant(provider, headers, payload)`` and calling it with
    ``request.headers`` is the normal shape — and it is the shape the real
    lead-management webhook resolver uses, which an assignment-only version of
    this function could not see.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                if arg.arg == "headers" or arg.arg.endswith("_headers"):
                    aliases.add(arg.arg)
        if isinstance(node, ast.Assign) and _is_headers_expr(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if _is_headers_expr(node.value) and isinstance(node.target, ast.Name):
                aliases.add(node.target.id)
    return aliases


class _RawHeaderReadVisitor(ast.NodeVisitor):
    """Finds reads of the tenant header off an inbound request/websocket.

    Deliberately does NOT flag outbound clients: building a headers dict to send
    to another service asserts nothing about the caller's identity. Only reads
    are trust decisions.
    """

    def __init__(self, header_aliases: set[str], headers_aliases: set[str]) -> None:
        self.hits: list[int] = []
        self._header_aliases = header_aliases
        self._headers_aliases = headers_aliases

    def _is_headers_target(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "headers":
            return True
        if isinstance(node, ast.Name) and node.id in self._headers_aliases:
            return True
        if isinstance(node, ast.Call):
            return any(self._is_headers_target(arg) for arg in node.args)
        return False

    def _is_key(self, node: ast.AST) -> bool:
        return _is_tenant_header_key(node, self._header_aliases)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        # <headers-ish>.get(<tenant header>)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and self._is_headers_target(func.value)
            and node.args
            and self._is_key(node.args[0])
        ):
            self.hits.append(node.lineno)

        # Header(..., alias=<tenant header>) — FastAPI param injection
        if isinstance(func, ast.Name) and func.id == "Header":
            for kw in node.keywords:
                if kw.arg == "alias" and self._is_key(kw.value):
                    self.hits.append(node.lineno)

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # <headers-ish>[<tenant header>]
        if self._is_headers_target(node.value) and self._is_key(node.slice):
            self.hits.append(node.lineno)
        self.generic_visit(node)


def scan_source_for_raw_tenant_header_reads(source: str) -> list[int]:
    """Line numbers in ``source`` that read the raw tenant header."""
    tree = ast.parse(source)
    visitor = _RawHeaderReadVisitor(_header_name_aliases(tree), _headers_aliases(tree))
    visitor.visit(tree)
    return visitor.hits


def find_raw_tenant_header_readers(app_root: Path) -> dict[str, list[int]]:
    """Map of ``app_root``-relative module path -> line numbers of raw reads."""
    found: dict[str, list[int]] = {}
    for path in iter_app_modules(app_root):
        # utf-8-sig: a BOM makes ast.parse raise SyntaxError on the first line.
        # One WAM module has one, and a crashing scan is a silently absent guard.
        hits = scan_source_for_raw_tenant_header_reads(
            path.read_text(encoding="utf-8-sig")
        )
        if hits:
            found[str(path.relative_to(app_root))] = hits
    return found


def assert_no_undocumented_raw_tenant_header_reads(
    app_root: Path,
    allowlist: Mapping[str, Exemption],
) -> None:
    found = find_raw_tenant_header_readers(app_root)
    undocumented = {
        module: lines for module, lines in found.items() if module not in allowlist
    }
    assert not undocumented, (
        "New raw X-Tenant-ID read(s). The header is gateway-signed identity CONTEXT, "
        "not an authorization input — authorize on AuthContext.tenant_id instead. "
        "If the read is genuinely required, gate the route (service token or inline "
        f"HMAC) and add it to the allowlist with a machine-checkable reason:\n{undocumented}"
    )


def assert_no_stale_exemptions(
    app_root: Path,
    allowlist: Mapping[str, Exemption],
) -> None:
    """A documented exemption that no longer reads the header must be removed."""
    found = find_raw_tenant_header_readers(app_root)
    stale = set(allowlist) - set(found)
    assert not stale, (
        f"Allowlisted modules that no longer read the header: {sorted(stale)}"
    )


def assert_exemptions_are_machine_verified(
    app_root: Path,
    allowlist: Mapping[str, Exemption],
) -> None:
    """The claim each exemption rests on must be checkable, not merely stated."""
    for module, exemption in allowlist.items():
        assert len(exemption.reason) > _MIN_REASON_LENGTH, (
            f"{module}: exemption reason is too thin to review"
        )
        assert exemption.requires_symbols or exemption.must_be_inert, (
            f"{module}: exemption rests on prose alone. State a gating symbol in "
            "requires_symbols, or set must_be_inert=True."
        )

        source = (app_root / module).read_text(encoding="utf-8-sig")

        for symbol in exemption.requires_symbols:
            assert symbol in source, (
                f"{module} reads the raw tenant header but no longer references "
                f"{symbol!r} — the gate its exemption depends on is gone. Restore "
                "the gate or remove the raw read."
            )

        if exemption.must_be_inert:
            markers = _NON_INERT_IMPORT_MARKERS + exemption.extra_non_inert_markers
            offenders = [
                ast.dump(node)
                for node in ast.walk(ast.parse(source))
                if isinstance(node, (ast.Import, ast.ImportFrom))
                and any(marker in ast.dump(node) for marker in markers)
            ]
            assert not offenders, (
                f"{module} is exempt only while it is inert, but it now imports a "
                "repository/service/DB session. An unverified tenant header can "
                f"reach data from here — gate the route first:\n{offenders}"
            )
