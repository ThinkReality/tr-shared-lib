"""Refuse to write shared migration history from an unmerged revision.

The fleet runs every service against ONE shared cloud database, so applied
migration history is global mutable state while branch state is per-checkout.
Applying a revision from a feature branch writes global state another checkout
cannot resolve — and, worse than the loud ``Can't locate revision``, an ALTER can
silently change a shape that older code is still reading, with no error anywhere.

The rule enforced here: **a revision may only be applied to a shared database
once it is on the integration branch, byte for byte.**

Three conditions must ALL hold before this refuses, and each one exists to let a
legitimate caller through:

1. **The target is not local.** The integration lane replays unmerged migrations
   against a throwaway container on purpose.
2. **The command writes history** — ``upgrade``, ``downgrade``, ``stamp``.
   ``revision --autogenerate`` connects to the shared database but only reads it,
   and blocking it would make the SECOND migration on any branch impossible: the
   first one is unmerged by definition. ``--sql`` (offline) never connects at
   all and is how a migration gets reviewed before merge.
3. **We are inside a git checkout.** Production and staging apply migrations from
   the Docker image (``docker-entrypoint.sh`` / ``deploy.sh``), which has neither
   ``.git`` (excluded by ``.dockerignore``) nor a ``git`` binary (installed only
   in the builder stage). An image is built from a commit and has no branch state
   to be wrong about, so no checkout means nothing to prove and the guard steps
   aside. Without this the gate would crash-loop every deploy in the fleet.

Comparison is by **blob hash, not filename**. Presence alone would miss the exact
case this exists for: editing an existing, not-yet-applied revision to add an
ALTER, then applying it. Every other checkout still holds the old file, the
version table says the revision is applied, and nothing errors.

Call it from ``alembic/env.py`` at the single point that file resolves its URL,
so both ``run_migrations_offline`` and ``run_migrations_online`` are covered::

    from alembic import context

    assert_migrations_are_merged(
        url, Path(__file__).parent / "versions", alembic_context=context
    )
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tr_shared.db.utils import is_local_dsn

__all__ = ["HISTORY_WRITING_ALEMBIC_FNS", "assert_migrations_are_merged"]

HISTORY_WRITING_ALEMBIC_FNS = frozenset({"upgrade", "downgrade", "do_stamp"})
"""``__name__`` of the callables Alembic passes as ``fn`` for history-writing commands.

Verified against Alembic 1.18.4 ``command.py``: ``upgrade`` → ``upgrade``,
``downgrade`` → ``downgrade``, ``stamp`` → ``do_stamp``. The read-only commands
that still open a connection are ``revision``/``check`` → ``retrieve_migrations``,
``current`` → ``display_version``, ``merge`` → ``nothing`` and ``ensure_version``
→ ``do_ensure_version``; none of them appear here, which is what keeps
autogenerate working on a branch.

``context_opts["fn"]`` is used rather than ``config.cmd_opts`` because
``cmd_opts`` is ``None`` whenever Alembic is driven through its Python API —
which is exactly how every service's ``app/cli/migrate.py`` runner drives it.
"""


def _unwrap_alembic_context(alembic_context: Any) -> Any:
    """Return the real ``EnvironmentContext`` behind ``alembic.context``.

    ``alembic.context`` is a MODULE-level proxy, and it only proxies *callables*
    plus class-level non-callables (``langhelpers._add_proxied_attribute``).
    ``context_opts`` is set in ``EnvironmentContext.__init__``, so it is an
    INSTANCE attribute and never appears on the proxy — reading it there raises
    ``AttributeError`` and, because this guard fails closed, every command would
    be treated as a history write.

    ``_install_proxy`` does publish the live instance as ``_proxy`` for the
    duration of a run, which is the only route to it. Verified against Alembic
    1.18.4: inside ``env.py``, ``context._proxy`` is the ``EnvironmentContext``
    and ``context_opts["fn"].__name__`` is ``display_version`` for ``current``
    and ``upgrade`` for ``upgrade``.

    Callers that already hold a real ``EnvironmentContext`` are passed through
    unchanged. Outside a run ``_proxy`` is absent or ``None``, which leaves the
    caller's object in place and lets the fail-closed path do its job.
    """
    return getattr(alembic_context, "_proxy", None) or alembic_context


def _is_history_write(alembic_context: Any) -> bool:
    """Whether this Alembic invocation will write the version table.

    Unknown counts as a write. This decides whether a guard runs, so an
    unrecognised Alembic version must fail closed and be loud, never open and
    silent.
    """
    if alembic_context is None:
        return True
    ctx = _unwrap_alembic_context(alembic_context)
    try:
        if ctx.is_offline_mode():
            return False
        fn = ctx.context_opts.get("fn")
    except (AttributeError, TypeError):
        return True
    name = getattr(fn, "__name__", None)
    if name is None:
        return True
    return name in HISTORY_WRITING_ALEMBIC_FNS


def _revision_files(versions_dir: Path) -> list[Path]:
    """Top-level ``.py`` files only — exactly what Alembic treats as revisions.

    ``iterdir`` rather than ``rglob`` is deliberate and load-bearing: Alembic's
    ``ScriptDirectory._list_py_dir`` stops after the first level unless
    ``recursive_version_locations`` is set, and no tree in this fleet sets it.
    ``_archive/`` and ``__pycache__/`` therefore fall out of scope by the same
    rule Alembic itself applies, with no name filter to drift out of date.
    """
    return sorted(
        path
        for path in versions_dir.iterdir()
        if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run git, or return ``None`` if git is unavailable.

    ``check=False`` covers a non-zero exit; it does NOT cover a missing binary,
    which raises ``FileNotFoundError``. The runtime Docker image has no git at
    all, so that is a real path and must not surface as a traceback.
    """
    try:
        return subprocess.run(  # noqa: S603
            ("git", *args), cwd=cwd, capture_output=True, text=True, check=False
        )
    except (FileNotFoundError, NotADirectoryError):
        return None


def _redact(dsn: str) -> str:
    """Host and beyond only — a DSN carries a password."""
    return dsn.rsplit("@", 1)[-1]


def _merged_blobs(repo: Path, integration_ref: str, rel_dir: str) -> dict[str, str]:
    """Map ``path -> blob sha`` for *rel_dir* as of *integration_ref*.

    ``-z`` is required, not cosmetic: git quotes non-ASCII paths by default
    (``core.quotePath``), so a merged revision with an accented name would come
    back quoted, fail to match, and be reported as unmerged. Splitting on
    whitespace breaks the same way on a filename containing a space.
    """
    listing = _git(repo, "ls-tree", "-r", "-z", integration_ref, "--", rel_dir)
    if listing is None or listing.returncode != 0:
        detail = "git is unavailable" if listing is None else listing.stderr.strip()
        raise SystemExit(
            f"Refusing to write migration history on a shared database: could not "
            f"read {integration_ref} ({detail})."
        )
    blobs: dict[str, str] = {}
    for record in listing.stdout.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if len(parts) < 3:
            continue
        blobs[path] = parts[2]
    return blobs


def _local_blobs(repo: Path, files: list[Path]) -> list[str]:
    """Blob sha of each working-tree file, computed by git itself.

    ``git hash-object`` rather than hashlib so the repository's object format
    (sha1 vs sha256) is git's problem, not ours.
    """
    result = _git(repo, "hash-object", "--", *(str(path) for path in files))
    if result is None or result.returncode != 0:
        detail = "git is unavailable" if result is None else result.stderr.strip()
        raise SystemExit(
            f"Refusing to write migration history on a shared database: could not "
            f"hash local revisions ({detail})."
        )
    return result.stdout.split()


def assert_migrations_are_merged(
    dsn: str,
    versions_dir: Path | str,
    *,
    alembic_context: Any = None,
    integration_ref: str = "origin/stage",
) -> None:
    """Raise ``SystemExit`` if this run would write history from an unmerged revision.

    Returns without checking anything when the target is local, when the command
    does not write the version table, or when there is no git checkout to compare
    against — see this module's docstring for why each of those is a legitimate
    caller rather than a hole.

    *alembic_context* is Alembic's ``context`` proxy, used to tell ``upgrade``
    from ``revision --autogenerate``. Omitting it means every invocation is
    treated as a write.

    *integration_ref* defaults to ``origin/stage``, the services' integration
    branch; the two shared libs integrate on ``origin/main``.

    Never fetches — a network round-trip on every Alembic run is not acceptable,
    so a stale ref is handled by telling the operator to fetch.
    """
    if is_local_dsn(dsn):
        return
    if not _is_history_write(alembic_context):
        return

    versions = Path(versions_dir).resolve()
    if not versions.is_dir():
        return

    toplevel = _git(versions, "rev-parse", "--show-toplevel")
    if toplevel is None or toplevel.returncode != 0:
        # No git, or no checkout: the deploy image. Nothing to prove.
        return
    repo = Path(toplevel.stdout.strip()).resolve()

    ref_check = _git(repo, "rev-parse", "--verify", "--quiet", integration_ref)
    if ref_check is None or ref_check.returncode != 0:
        raise SystemExit(
            f"Refusing to write migration history on a shared database ({_redact(dsn)}): "
            f"{integration_ref} does not exist in this checkout, so nothing can be "
            "proven merged.\n"
            f"Run `git fetch origin {integration_ref.rsplit('/', 1)[-1]}` and try again."
        )

    files = _revision_files(versions)
    if not files:
        return

    merged = _merged_blobs(repo, integration_ref, versions.relative_to(repo).as_posix())
    local = _local_blobs(repo, files)

    absent: list[str] = []
    modified: list[str] = []
    for path, sha in zip(files, local, strict=True):
        rel = path.relative_to(repo).as_posix()
        if rel not in merged:
            absent.append(path.name)
        elif merged[rel] != sha:
            modified.append(path.name)

    if not absent and not modified:
        return

    problems = ""
    if absent:
        problems += "\n\nNot on {ref}:\n  " + "\n  ".join(absent)
    if modified:
        problems += (
            "\n\nChanged since {ref} — the shared database would get DDL no "
            "other checkout has:\n  " + "\n  ".join(modified)
        )

    raise SystemExit(
        f"Refusing to write migration history on a shared database ({_redact(dsn)})."
        + problems.format(ref=integration_ref)
        + "\n\nApplied migration history on the shared database is global state, but "
        "these revisions exist only in this checkout. Applying them leaves every other "
        "checkout unable to resolve the revision — and an ALTER can silently change a "
        "shape that older code is still reading.\n\n"
        "Merge first, then apply. Correctness before merge is the integration lane's "
        "job: it replays the full chain against a throwaway container. If "
        f"{integration_ref} is merely stale here, run "
        f"`git fetch origin {integration_ref.rsplit('/', 1)[-1]}`."
    )
