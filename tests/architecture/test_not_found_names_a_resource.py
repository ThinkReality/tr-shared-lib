from pathlib import Path

from tr_shared.testing import assert_not_found_names_a_resource

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "tr_shared"


def test_every_not_found_error_names_a_resource():
    assert_not_found_names_a_resource(SRC_ROOT)
