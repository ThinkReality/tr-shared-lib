from __future__ import annotations

from pathlib import Path

from tr_shared.testing.guards import Exemption, assert_no_infra_skips

TESTS_ROOT = Path(__file__).resolve().parents[1]

ALLOWLIST: dict[str, Exemption] = {}


def test_no_infra_skips() -> None:
    assert_no_infra_skips(TESTS_ROOT, ALLOWLIST)
