from pathlib import Path

import tr_shared
from tr_shared.testing.guards import Exemption, assert_error_codes_carry_prefix

LIB_ROOT = Path(tr_shared.__file__).resolve().parent

DOMAIN_PREFIXES = {
    "contracts/availability.py": "DATABASE",
    "http/internal_client.py": "INTERNAL_CLIENT",
    "integrations/hikcentral.py": "HIKCENTRAL",
    "integrations/portal_errors.py": "PORTAL",
    "webhooks": "WEBHOOK",
}

SUFFIXES = {
    "schemas/error_envelope.py": Exemption(
        reason="Holds the {CATEGORY}_000 suffixes the handler appends to a service's prefix.",
        requires_symbols=("VALIDATION_CODE", "INTERNAL_CODE", "CONFLICT_CODE"),
    ),
}


def test_the_libs_own_error_codes_follow_the_standard() -> None:
    assert_error_codes_carry_prefix(LIB_ROOT, "TR_SHARED", DOMAIN_PREFIXES, SUFFIXES)
