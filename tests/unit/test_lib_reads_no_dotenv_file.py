from pathlib import Path

from tr_shared.testing import guards

LIB_REPO = Path(__file__).resolve().parents[2]


def test_the_lib_reads_no_dotenv_file() -> None:
    guards.assert_no_dotenv_loading(LIB_REPO)
