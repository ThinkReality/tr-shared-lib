from pathlib import Path

from tr_shared.testing import guards
from tr_shared.testing.guards import Exemption

LIB_REPO = Path(__file__).resolve().parents[2]

REMOVED_IN_L5 = {
    "src/tr_shared/config/base.py": Exemption(
        reason="BaseServiceSettings still reads .env; L5 drops env_file.",
        requires_symbols=('env_file=".env"',),
    ),
    "tests/config/test_env_audit.py": Exemption(
        reason="Redundant env_file=None in test classes; L5 deletes them.",
        requires_symbols=("env_file=None",),
    ),
    "tests/testing/test_env_contract.py": Exemption(
        reason="Redundant env_file=None in test classes; L5 deletes them.",
        requires_symbols=("env_file=None",),
    ),
}


def test_the_lib_reads_no_dotenv_file() -> None:
    guards.assert_no_dotenv_loading(LIB_REPO, allowlist=REMOVED_IN_L5)
