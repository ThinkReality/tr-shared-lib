"""G14: a run must use the repo's own ``.venv``, or stop.

Eight services sit side by side here, each with its own ``.venv``. Activate one — or let
an editor activate it — and ``VIRTUAL_ENV`` plus a ``PATH`` entry follow you into every
other service, where ``uv run pytest`` resolves the ``pytest`` executable out of the
activated venv and the session imports from its ``site-packages``.

The symptom is a lie. tr-people-finance reported 74 collection errors for a missing
``email_validator`` while that package sat installed in its own venv the whole time; the
run was using tr-media-service's, which does not need it. The only clue is the other
service's path buried in the traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tr_shared.testing.plugin import _assert_venv_belongs_to_this_service


def test_no_venv_in_the_repo_is_not_an_error(tmp_path: Path) -> None:
    """Docker images and CI install into the system environment. There is no ``.venv``
    to disagree with, so there is nothing to assert."""
    _assert_venv_belongs_to_this_service(tmp_path)


def test_a_file_named_venv_is_not_a_venv(tmp_path: Path) -> None:
    (tmp_path / ".venv").write_text("not a directory")

    _assert_venv_belongs_to_this_service(tmp_path)


def test_the_repos_own_venv_passes(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    venv.mkdir()

    with _prefix(venv):
        _assert_venv_belongs_to_this_service(tmp_path)


def test_another_services_venv_is_refused(tmp_path: Path) -> None:
    this_service = tmp_path / "tr-people-finance"
    other_service = tmp_path / "tr-media-service"
    (this_service / ".venv").mkdir(parents=True)
    (other_service / ".venv").mkdir(parents=True)

    with _prefix(other_service / ".venv"), pytest.raises(SystemExit) as exc:
        _assert_venv_belongs_to_this_service(this_service)

    message = str(exc.value)
    assert "tr-people-finance" in message
    assert "tr-media-service" in message


def test_the_refusal_names_both_paths_and_how_to_fix_it(tmp_path: Path) -> None:
    """The whole value of this guard is that the message beats the symptom it replaces.
    An ``ImportError`` for a package that is installed sends you to the wrong place."""
    this_service = tmp_path / "svc"
    other = tmp_path / "other"
    (this_service / ".venv").mkdir(parents=True)
    other.mkdir()

    with _prefix(other), pytest.raises(SystemExit) as exc:
        _assert_venv_belongs_to_this_service(this_service)

    message = str(exc.value)
    assert str((this_service / ".venv").resolve()) in message
    assert str(other.resolve()) in message
    assert "deactivate" in message


def test_a_symlinked_path_to_the_same_venv_is_accepted(tmp_path: Path) -> None:
    """Both sides resolve before comparing. A venv reached through a symlinked checkout
    is the same venv, and failing that would make the guard worse than the bug."""
    real = tmp_path / "real"
    (real / ".venv").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with _prefix(link / ".venv"):
        _assert_venv_belongs_to_this_service(real)


class _prefix:
    """Swap ``sys.prefix`` for the duration of the block."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def __enter__(self) -> None:
        self._original = sys.prefix
        sys.prefix = str(self._path)

    def __exit__(self, *_exc: object) -> None:
        sys.prefix = self._original
