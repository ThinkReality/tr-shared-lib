"""Reusable structural guards for service test suites.

These are not runtime helpers. They are AST-based checks that a service's own
test suite runs over its own ``app/`` tree, so a fleet-wide invariant fails in
the service that breaks it rather than in a distant reviewer's memory.
"""

from tr_shared.testing.tenant_header_guard import (
    Exemption,
    assert_exemptions_are_machine_verified,
    assert_no_stale_exemptions,
    assert_no_undocumented_raw_tenant_header_reads,
    find_raw_tenant_header_readers,
    iter_app_modules,
    scan_source_for_raw_tenant_header_reads,
)

__all__ = [
    "Exemption",
    "assert_exemptions_are_machine_verified",
    "assert_no_stale_exemptions",
    "assert_no_undocumented_raw_tenant_header_reads",
    "find_raw_tenant_header_readers",
    "iter_app_modules",
    "scan_source_for_raw_tenant_header_reads",
]
