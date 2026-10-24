from pathlib import Path

from tr_shared.testing import Exemption, assert_no_local_client_ip_derivation

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "tr_shared"

ALLOWLIST = {
    "client_ip.py": Exemption(
        reason="The fleet client-IP rule itself: the one place that reads the IP headers and the peer.",
        requires_symbols=("GATEWAY_VERIFIED", "RESOLVED_CLIENT_IP"),
    ),
    "contracts/headers.py": Exemption(
        reason="Declares the header names every service and the frontend contract are generated from.",
        requires_symbols=("class HttpHeader",),
    ),
}


def test_only_the_fleet_rule_derives_the_client_ip():
    assert_no_local_client_ip_derivation(SRC_ROOT, ALLOWLIST)
