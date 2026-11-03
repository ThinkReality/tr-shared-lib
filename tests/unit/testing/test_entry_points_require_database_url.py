"""Every start-script module and every tracked alembic.ini must refuse DATABASE_URL=""."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tr_shared.testing import assert_entry_points_require_database_url, role_dispatch

_CONFIG = """\
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = Field(min_length=1)
"""
_BUILDS_SETTINGS = "from app.core.config import Settings\n\nSettings()\n"
_CONSUMER = """\
import time

from app.core.config import Settings


def main():
    Settings()
    time.sleep(60)


if __name__ == "__main__":
    main()
"""
_ALEMBIC_MAIN = """\
import sys

assert sys.argv[1:] == ["-c", "migrations/alembic.ini", "current"], sys.argv
from app.core.config import Settings

Settings()
"""


def _service(
    root: Path,
    *,
    main: str = _BUILDS_SETTINGS,
    consumer: str = _CONSUMER,
    alembic_main: str = _ALEMBIC_MAIN,
    deploy: str | None = "exec uvicorn app.main:app\nexec python -m app.consumer\n",
) -> Path:
    files = {
        "app/__init__.py": "",
        "app/core/__init__.py": "",
        "app/core/config.py": _CONFIG,
        "app/main.py": main,
        "app/consumer.py": consumer,
        "alembic/__init__.py": "",
        "alembic/__main__.py": alembic_main,
        "migrations/alembic.ini": "[alembic]\n",
    }
    if deploy is not None:
        files["deploy.sh"] = deploy
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def test_a_service_whose_entry_points_all_refuse_passes(tmp_path: Path) -> None:
    assert_entry_points_require_database_url(_service(tmp_path))


def test_an_imported_module_that_starts_fails(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="python -c import app.main: exit 0"):
        assert_entry_points_require_database_url(_service(tmp_path, main=""))


def test_a_python_m_module_still_running_at_the_timeout_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(role_dispatch, "STARTUP_TIMEOUT_SECONDS", 2)
    consumer = "import time\n\nif __name__ == '__main__':\n    time.sleep(60)\n"
    with pytest.raises(AssertionError, match="python -m app.consumer: still running after 2 s"):
        assert_entry_points_require_database_url(_service(tmp_path, consumer=consumer))


def test_alembic_that_starts_fails(tmp_path: Path) -> None:
    with pytest.raises(
        AssertionError, match="python -m alembic -c migrations/alembic.ini current: exit 0"
    ):
        assert_entry_points_require_database_url(_service(tmp_path, alembic_main=""))


def test_a_validation_error_for_a_class_that_is_not_a_settings_class_fails(
    tmp_path: Path,
) -> None:
    main = (
        "from pydantic import BaseModel, Field\n\n\n"
        "class Other(BaseModel):\n    DATABASE_URL: str = Field(min_length=1)\n\n\n"
        "Other(DATABASE_URL='')\n"
    )
    with pytest.raises(AssertionError, match=r"python -c import app\.main: exit 1.*\['Settings'\]"):
        assert_entry_points_require_database_url(_service(tmp_path, main=main))


def test_a_repo_without_a_start_script_fails(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="no deploy.sh or docker-entrypoint.sh"):
        assert_entry_points_require_database_url(_service(tmp_path, deploy=None))
