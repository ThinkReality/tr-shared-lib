"""The merge gate refuses to write shared history from an unmerged revision.

Every test builds a REAL git repo in tmp_path rather than mocking subprocess:
the whole guard is a statement about git's answers, so stubbing git would test
the stub. ``git update-ref refs/remotes/origin/stage`` fabricates the integration
ref without needing a second repository.
"""

import subprocess
from pathlib import Path

import pytest

from tr_shared.db import assert_migrations_are_merged
from tr_shared.db.migrations.merge_gate import HISTORY_WRITING_ALEMBIC_FNS

_REMOTE = "postgresql+asyncpg://user:sup3rs3cret@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
_LOCAL = "postgresql+asyncpg://u:p@localhost:5432/db"


class _Ctx:
    """Stands in for Alembic's ``context`` proxy.

    Only the two attributes the guard reads are modelled. ``fn`` is matched by
    ``__name__``, so a plain function with the right name is a faithful double —
    ``test_the_writing_fn_names_match_the_installed_alembic`` is what keeps that
    faithful to the real Alembic rather than to this class.
    """

    def __init__(self, fn_name: str | None = "upgrade", *, offline: bool = False):
        self.context_opts = {"fn": None}
        if fn_name is not None:
            fn = type("_fn", (), {})
            fn.__name__ = fn_name
            self.context_opts["fn"] = fn
        self._offline = offline

    def is_offline_mode(self) -> bool:
        return self._offline


class _ProxyCtx:
    """Models `alembic.context` — the MODULE-level proxy env.py actually holds.

    The proxy exposes only callables and class-level non-callables, so
    `context_opts` (an instance attribute) is NOT reachable on it; the live
    `EnvironmentContext` is published as `_proxy` for the duration of a run.
    Reading `context_opts` off the proxy raises AttributeError and, since the
    guard fails closed, every command reads as a history write — which is
    exactly how `alembic current` got blocked in tr-crm-core before this shape
    was modelled here.
    """

    def __init__(self, inner: _Ctx | None):
        if inner is not None:
            self._proxy = inner

    def __getattr__(self, name: str):  # everything else is genuinely absent
        raise AttributeError(name)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    """A git repo whose single migration is committed and on origin/stage."""
    repo = tmp_path / "svc"
    versions = repo / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_first.py").write_text("revision = '0001'\n")
    _git(repo, "init", "-q", "-b", "stage")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    _git(repo, "update-ref", "refs/remotes/origin/stage", "HEAD")
    return repo


def _versions(repo: Path) -> Path:
    return repo / "alembic" / "versions"


def _assert(dsn, versions, **kw):
    kw.setdefault("alembic_context", _Ctx("upgrade"))
    return assert_migrations_are_merged(dsn, versions, **kw)


# --- Condition 1: locality ------------------------------------------------


def test_local_dsn_is_never_blocked_even_with_an_unmerged_revision(tmp_path):
    """The integration lane replays unmerged migrations against a container on
    purpose, and CI may have no origin/stage ref. Locality is checked BEFORE git
    is touched."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    _assert(_LOCAL, _versions(repo))


# --- Condition 2: only history-writing commands ---------------------------


@pytest.mark.parametrize("fn_name", sorted(HISTORY_WRITING_ALEMBIC_FNS))
def test_history_writing_commands_are_gated(tmp_path, fn_name):
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    with pytest.raises(SystemExit):
        _assert(_REMOTE, _versions(repo), alembic_context=_Ctx(fn_name))


@pytest.mark.parametrize(
    "fn_name",
    ["retrieve_migrations", "display_version", "nothing", "do_ensure_version"],
)
def test_read_only_commands_are_not_gated(tmp_path, fn_name):
    """`revision --autogenerate` (retrieve_migrations) connects to the shared DB
    but only reads it. Gating it would make the SECOND migration on any branch
    impossible, since the first is unmerged by definition."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    _assert(_REMOTE, _versions(repo), alembic_context=_Ctx(fn_name))


def test_offline_sql_generation_is_not_gated(tmp_path):
    """`alembic upgrade X:Y --sql` never connects — and it is how a migration
    gets reviewed before merge."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    _assert(_REMOTE, _versions(repo), alembic_context=_Ctx("upgrade", offline=True))


@pytest.mark.parametrize("ctx", [None, _Ctx(None), object()])
def test_an_undeterminable_command_fails_closed(tmp_path, ctx):
    """Unknown must be loud, never silently open: a future Alembic that moves
    context_opts must break the guard visibly rather than disable it."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    with pytest.raises(SystemExit):
        assert_migrations_are_merged(_REMOTE, _versions(repo), alembic_context=ctx)


@pytest.mark.parametrize(
    "fn_name",
    ["retrieve_migrations", "display_version", "nothing", "do_ensure_version"],
)
def test_read_only_commands_are_not_gated_through_the_module_proxy(tmp_path, fn_name):
    """The regression that shipped: env.py holds the PROXY, not the
    EnvironmentContext. Reading `context_opts` off the proxy raises, the guard
    fails closed, and `alembic current` gets blocked on any branch holding an
    unmerged migration."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    _assert(_REMOTE, _versions(repo), alembic_context=_ProxyCtx(_Ctx(fn_name)))


def test_history_writing_commands_are_still_gated_through_the_module_proxy(tmp_path):
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    with pytest.raises(SystemExit):
        _assert(_REMOTE, _versions(repo), alembic_context=_ProxyCtx(_Ctx("upgrade")))


def test_a_proxy_with_no_live_instance_fails_closed(tmp_path):
    """Outside a run `_proxy` is absent — nothing can be determined, so treat it
    as a write rather than waving it through."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    with pytest.raises(SystemExit):
        _assert(_REMOTE, _versions(repo), alembic_context=_ProxyCtx(None))


def test_the_writing_fn_names_are_pinned():
    """Alembic is NOT a dependency of this library — the migration helpers import
    it lazily — so the set cannot be checked against the real thing here.

    Each consuming service's ``tests/architecture/test_migration_guard_wired.py``
    asserts it against its own installed Alembic, which is where the drift would
    actually bite. This test only pins the value so a careless edit to the
    frozenset is visible in a diff.
    """
    assert HISTORY_WRITING_ALEMBIC_FNS == {"upgrade", "downgrade", "do_stamp"}


# --- Condition 3: a git checkout must exist -------------------------------


def test_no_git_checkout_is_allowed_because_that_is_the_deploy_image(tmp_path):
    """Production and staging run `alembic upgrade head` from the Docker image,
    which has neither .git (excluded by .dockerignore) nor a git binary
    (builder stage only). Blocking here would crash-loop every deploy."""
    versions = tmp_path / "image" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_first.py").write_text("revision = '0001'\n")

    _assert(_REMOTE, versions)


# --- The comparison itself ------------------------------------------------


def test_passes_when_every_revision_is_merged(tmp_path):
    repo = _repo(tmp_path)

    _assert(_REMOTE, _versions(repo))


def test_an_unmerged_revision_is_blocked(tmp_path):
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    with pytest.raises(SystemExit) as exit_info:
        _assert(_REMOTE, _versions(repo))

    message = str(exit_info.value)
    assert "0002_unmerged.py" in message
    assert "0001_first.py" not in message, "only the offending revision should be named"
    assert "origin/stage" in message


def test_a_committed_but_unpushed_revision_is_still_unmerged(tmp_path):
    """The realistic case: the work IS committed, just not on stage yet."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_committed.py").write_text("revision = '0002'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    with pytest.raises(SystemExit) as exit_info:
        _assert(_REMOTE, _versions(repo))

    assert "0002_committed.py" in str(exit_info.value)


def test_an_edited_existing_revision_is_blocked(tmp_path):
    """Failure mode C, the silent one. A presence-only check passes this: the
    filename is on stage, so nothing looks wrong — while the shared database
    gets DDL no other checkout has."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0001_first.py").write_text(
        "revision = '0001'\n# op.alter_column('a', 'b')\n"
    )

    with pytest.raises(SystemExit) as exit_info:
        _assert(_REMOTE, _versions(repo))

    message = str(exit_info.value)
    assert "0001_first.py" in message
    assert "Changed since" in message


def test_a_filename_with_a_space_is_matched_correctly(tmp_path):
    """git ls-tree output split on whitespace would report this MERGED file as
    unmerged. Same class of bug as quoted non-ASCII paths."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002 spaced.py").write_text("revision = '0002'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "spaced")
    _git(repo, "update-ref", "refs/remotes/origin/stage", "HEAD")

    _assert(_REMOTE, _versions(repo))


def test_a_non_ascii_filename_is_matched_correctly(tmp_path):
    """git quotes non-ASCII paths by default (core.quotePath), so without -z a
    MERGED file comes back quoted, fails to match, and is reported unmerged."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_café.py").write_text("revision = '0002'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "accented")
    _git(repo, "update-ref", "refs/remotes/origin/stage", "HEAD")

    _assert(_REMOTE, _versions(repo))


# --- Failure paths --------------------------------------------------------


def test_a_missing_integration_ref_blocks_rather_than_passes(tmp_path):
    """No origin/stage means nothing can be proven merged. Unknown must never
    read as safe on a shared target."""
    repo = _repo(tmp_path)
    _git(repo, "update-ref", "-d", "refs/remotes/origin/stage")

    with pytest.raises(SystemExit) as exit_info:
        _assert(_REMOTE, _versions(repo))

    assert "git fetch origin stage" in str(exit_info.value)


def test_a_missing_versions_directory_does_not_raise(tmp_path):
    repo = _repo(tmp_path)

    _assert(_REMOTE, repo / "alembic" / "does_not_exist")


def test_the_dsn_password_is_never_echoed(tmp_path):
    """The DSN carries a password and these messages get pasted into tickets."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_unmerged.py").write_text("revision = '0002'\n")

    with pytest.raises(SystemExit) as exit_info:
        _assert(_REMOTE, _versions(repo))

    message = str(exit_info.value)
    assert "sup3rs3cret" not in message
    assert "user" not in message
    assert "pooler.supabase.com" in message, "the host should still be named"


# --- Scope of what counts as a revision -----------------------------------


def test_only_top_level_python_files_count_as_revisions(tmp_path):
    """Matches Alembic: a versions/ directory is NOT scanned recursively unless
    recursive_version_locations is set, and no tree in this fleet sets it. An
    unmerged file inside _archive/ or __pycache__/ is out of scope because it is
    not a revision Alembic would run either."""
    repo = _repo(tmp_path)
    versions = _versions(repo)
    (versions / "__pycache__").mkdir()
    (versions / "__pycache__" / "0001_first.cpython-313.pyc").write_bytes(b"\x00")
    (versions / "_archive").mkdir()
    (versions / "_archive" / "0000_unmerged_archive.py").write_text("revision = '0000'\n")

    _assert(_REMOTE, versions)


def test_a_stray_non_python_file_is_not_a_revision(tmp_path):
    repo = _repo(tmp_path)
    (_versions(repo) / "notes.md").write_text("scratch\n")

    _assert(_REMOTE, _versions(repo))


def test_an_unmerged_init_py_is_not_a_revision(tmp_path):
    repo = _repo(tmp_path)
    (_versions(repo) / "__init__.py").write_text("")

    _assert(_REMOTE, _versions(repo))


# --- The integration ref is a real parameter ------------------------------


def test_the_integration_ref_is_actually_used_for_the_comparison(tmp_path):
    """Discriminating on purpose: origin/main carries a revision origin/stage
    does NOT. An implementation that hardcoded origin/stage in the comparison and
    merely interpolated the parameter into the message would fail here."""
    repo = _repo(tmp_path)
    (_versions(repo) / "0002_on_main_only.py").write_text("revision = '0002'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    # Merged on main → allowed when main is the integration branch.
    _assert(_REMOTE, _versions(repo), integration_ref="origin/main")

    # Still absent from stage → blocked under the default.
    with pytest.raises(SystemExit) as exit_info:
        _assert(_REMOTE, _versions(repo))
    assert "0002_on_main_only.py" in str(exit_info.value)
