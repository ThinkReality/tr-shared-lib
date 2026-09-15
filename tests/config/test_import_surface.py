"""The settings and pytest-plugin surface must import without the ``[db]`` extra.

shared-auth-lib pins ``tr-shared-lib[http,logging]`` and builds no engine, yet every one of
its test sessions loads ``tr_shared.testing`` (a ``pytest11`` entry point), which reaches
``tr_shared.config``. v0.78.0 made ``config.base`` import a constant from ``tr_shared.db``,
whose package ``__init__`` imports SQLAlchemy — and the auth lib's suite died at collection
with ``ModuleNotFoundError: No module named 'sqlalchemy'``. This lib's own venv has every
extra, so an in-process test cannot see that; the subprocess forbids the extra's packages.
"""

import subprocess
import sys

import pytest

_BLOCK_DB_EXTRA = """
import importlib.abc, sys

class _Forbid(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"sqlalchemy", "asyncpg"}:
            raise ModuleNotFoundError(f"[db] extra not installed: {name}")
        return None

sys.meta_path.insert(0, _Forbid())
import %s
"""


@pytest.mark.parametrize("module", ["tr_shared.config", "tr_shared.testing"])
def test_importable_without_the_db_extra(module: str):
    result = subprocess.run(
        [sys.executable, "-c", _BLOCK_DB_EXTRA % module],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
