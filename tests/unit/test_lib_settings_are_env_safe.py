from pathlib import Path

from tr_shared.testing import env_contract

LIB_REPO = Path(__file__).resolve().parents[2]


def test_the_libs_settings_are_env_safe() -> None:
    env_contract.assert_settings_are_env_safe(LIB_REPO, package="src/tr_shared")
