from pathlib import Path

from tr_shared.testing import assert_no_raw_http_exceptions

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "tr_shared"


def test_the_library_never_constructs_a_raw_http_exception():
    assert_no_raw_http_exceptions(SRC_ROOT)
