"""Test infrastructure shared by every service.

Two things live here, and they are unrelated in mechanism but not in purpose:

* **The lane/stack machinery** (``config``, ``lanes``, ``stack``, ``plugin``) —
  provisions real Postgres and Redis for the integration lane, and makes the unit
  lane structurally incapable of reaching a database. Normative description:
  ``docs/shared/TR_Testing_Standard.md``.
* **Structural guards** (``guards``, ``tenant_header_guard``) — AST checks a
  service's own suite runs over its own tree, so a fleet-wide invariant fails in
  the service that breaks it rather than in a distant reviewer's memory.
* **Isolation** (``isolation``, ``fixtures``) — savepoint-rolled-back sessions and
  a Redis index per xdist worker.

Auth test helpers live in ``shared_auth_lib.testing``, not here: they depend on
``compute_signature`` and ``AuthContextProvider``, which shared-auth-lib owns, and
shared-auth-lib depends on this library — so placing them here would invert the
layering and leave them untestable in the repo that owns their contract.

Nothing here is imported by production code, and ``plugin`` imports ``stack``
lazily, so a service that has not opted in never needs the ``testing`` extra
installed.
"""

from tr_shared.testing.config import TestingConfig, find_config
from tr_shared.testing.guards import (
    assert_no_auth_chain_bypass,
    assert_no_env_mutation_in_conftest,
    assert_no_infra_skips,
    assert_no_ryuk_disabled,
    assert_no_schema_construction,
    assert_no_sqlite_dsn,
    assert_no_testing_flag_in_production,
)
from tr_shared.testing.isolation import (
    redis_index_for_worker,
    savepoint_session,
    worker_id,
)
from tr_shared.testing.lanes import (
    POISON_DATABASE_URL,
    POISON_REDIS_URL,
    lane_for_path,
    run_needs_infrastructure,
)
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
    "POISON_DATABASE_URL",
    "POISON_REDIS_URL",
    "Exemption",
    "TestingConfig",
    "assert_exemptions_are_machine_verified",
    "assert_no_auth_chain_bypass",
    "assert_no_env_mutation_in_conftest",
    "assert_no_infra_skips",
    "assert_no_ryuk_disabled",
    "assert_no_schema_construction",
    "assert_no_sqlite_dsn",
    "assert_no_testing_flag_in_production",
    "assert_no_stale_exemptions",
    "assert_no_undocumented_raw_tenant_header_reads",
    "find_config",
    "find_raw_tenant_header_readers",
    "iter_app_modules",
    "lane_for_path",
    "redis_index_for_worker",
    "run_needs_infrastructure",
    "savepoint_session",
    "worker_id",
    "scan_source_for_raw_tenant_header_reads",
]
