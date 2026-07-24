# Plan 0 — `tr-shared-lib` Portal Sync Activity S2S Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `portal_sync_status` vocabulary and the `/portal-publications/recent-sync-activity` S2S contract — path builder, query model, response models — to `tr_shared.contracts.s2s.listing_internal`, so `tr-content-platform` (producer) and `tr-crm-core` (consumer) share one declaration instead of two disagreeing ones.

The endpoint is specified end to end on purpose: path, query, and response. Pinning only the path and the response leaves the four query parameters hand-declared on both sides, where a drifted key (`sync_status` vs `status_filter`) returns HTTP 200 with the filter silently ignored — the same failure class as the enum disagreement below, moved from the value to the key.

**Architecture:** Pure additive change to one existing contract module plus its test file. No runtime behaviour in this repo — `contracts/s2s/` is a declarations-only package (stdlib + pydantic, nothing else). One `BASE_PATH` rename inside the module makes room for a second resource prefix under the same provider root.

**Tech Stack:** Python 3.13, `StrEnum`, Pydantic v2, pytest, mypy (baseline-ratchet gate).

## Global Constraints

- **No git operations.** Never run `git add`, `git commit`, `git push`. The user pushes manually. This plan ends with a handoff, not a commit.
- **Repo is `tr-shared-lib`.** Every command runs from `/Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib`. Never from `/Backend` root.
- **Use `.venv/bin/python -m pytest`, never `uv run pytest`.** `uv run` re-syncs the environment from the git pin and can silently swap the package under you.
- **Pytest needs `-o "addopts="`** on targeted runs — the repo-level `addopts` turns on `--cov` with an 80% `fail_under`, which a 4-test run cannot clear.
- **No `ruff` in this repo.** It is not a dev dependency and CI has no lint job (`.github/workflows/ci.yml` = `typecheck` + `test` only). Do not invent a lint step. Match surrounding style by hand: double quotes, 4-space indent, `from __future__ import annotations` only where the file already has it (`listing_internal.py` does **not**).
- **`contracts/` must not import `tr_shared.integrations`.** See Task 2 Step 4 for why — this is a hard layering rule, not a preference.
- **mypy gate is a ratchet.** `uv run mypy src/tr_shared/ | uv run mypy-baseline filter` fails only on errors absent from `mypy-baseline.txt`. New code must produce **zero** new errors. Never regenerate the baseline to hide one.
- **Target version: `0.39.0` → `0.40.0`.** Additive, no breaking change.

---

## Why this plan exists

Plan 2 (`tr-content-platform/plans/2026-07-24-plan-2-*.md`) moves `tr-crm-core`'s "recent sync activity" admin endpoint off a raw cross-schema SQL read and onto an S2S call. Two facts force a shared-lib change first:

**1. The S2S route+model SSOT rule already applies.** `tr_shared/contracts/s2s/__init__.py` states it verbatim:

> Each module here owns one provider's internal contract: the route PATHS (as builder functions, so a caller can never hardcode a path that drifts from the provider → kills the silent-404 class) and the request/response MODELS the two sides agree on (so a renamed field is a type error, not a silent `None`).

`tr-crm-core/app/modules/admin/clients/listing_client.py:6` already imports from this module. A new S2S endpoint belongs here — hardcoding its path in the consumer is the exact failure mode the rule exists to prevent.

**2. `portal_sync_status` is currently declared twice, wrongly.**

| Where | Values |
|---|---|
| `tr-content-platform/app/modules/listing/core/enums.py:62-68` — the owner, CHECK-constrained in the DB | `pending`, `syncing`, `synced`, `error`, `disabled`, `action_required` |
| `tr-crm-core/app/modules/admin/schemas/integrations.py:25-28` (`RecentSyncStatus`) — the consumer | `success`, `failed`, `pending` |

Two live defects follow directly from that disagreement (both fixed in Plan 2, both impossible to reintroduce after this plan):

- `status_filter=success` / `=failed` validate at the crm-core edge, then match zero rows in SQL.
- `_SYNC_STATUS_DESCRIPTIONS` (`platform_monitoring_routes.py:23-26`) is keyed by `RecentSyncStatus` members but looked up with the raw `portal_sync_status` value → **every** row renders the fallback `"Sync pending to {portal}"`.

Since the shared-lib round-trip is unavoidable for (1), carrying the enum in the same push costs one extra symbol and removes the whole defect class.

**3. Without a query model, the wrong enum survives.** `RecentSyncStatus` has exactly five usages in `tr-crm-core`: its declaration, its import, the two `_SYNC_STATUS_DESCRIPTIONS` keys, and `platform_monitoring_routes.py:78`, which validates `status_filter` against it. Plan 2 deletes the description-map uses. Line 78 does not die unless the query vocabulary is also shared — so the duplicate declaration this plan exists to remove would live on in the filter path, still spelling `success`/`failed`. `PortalSyncActivityQuery.sync_status: PortalSyncStatus | None` is what actually kills it, and it deletes the hand-rolled validation branch and its `ValidationError` raise along with it.

The same applies to the bounds. `limit` (`ge=1, le=100`) and `hours_back` (`ge=1, le=168`) are business contract, declared today on the consumer route and — before this change — destined to be hand-written a second time on the new provider route. `Field(20, ge=1, le=100)` in the contract makes that one declaration. FastAPI ≥0.115 consumes the model directly as `Annotated[PortalSyncActivityQuery, Query()]`; both repos run 0.136.3 against a `>=0.115.12` floor. `extra="forbid"` makes an unrecognised key a 422 rather than a silent no-op.

**Precedent:** `AssignmentMethod` (`contracts/s2s/admin_internal.py:58`) is the identical shape — a vocabulary the producer owns that the consumer filters and renders — and it was promoted here in 0.39.0.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/tr_shared/contracts/s2s/listing_internal.py` | S2S contract for `tr-content-platform`'s `/api/v1/listing/internal` | Add `PortalSyncStatus`, `recent_sync_activity()`, `PortalSyncActivityQuery`, `PortalSyncActivityRow`, `PortalSyncActivityPage`; split `BASE_PATH` into three named prefixes |
| `tests/contracts/s2s/test_listing_internal.py` | Contract tests for that module | Add path + vocabulary + model tests |
| `pyproject.toml` | Package metadata | `version = "0.40.0"` |
| `CHANGELOG.md` | Release notes | New `## [0.40.0]` entry at top |
| `.github/workflows/ci.yml` | CI | Add `tests/contracts` to the pytest scope |

**Not touched:** `src/tr_shared/contracts/s2s/__init__.py`. It re-exports only `access_check`; every other contract module is imported by its full path (`from tr_shared.contracts.s2s.listing_internal import ...`), which is how both consumers already do it. Adding re-exports would create a second import path for the same symbol — the duplication this plan exists to remove.

---

## Task 1: Baseline, then write the failing contract tests

**Files:**
- Test: `tests/contracts/s2s/test_listing_internal.py` (modify — currently 3 tests, 24 lines)

**Interfaces:**
- Produces: nothing yet. Establishes the RED state Task 2 turns GREEN.

- [ ] **Step 1: Capture the test baseline**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
.venv/bin/python -m pytest tests/contracts -o "addopts=" -q 2>&1 | tail -5
```

Expected: `31 passed` in well under a second. If anything fails here, stop — it is pre-existing and must be reported before continuing.

- [ ] **Step 2: Capture the mypy baseline**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
set +o pipefail
.venv/bin/mypy src/tr_shared/ | .venv/bin/mypy-baseline filter 2>&1 | tail -5
```

Expected: the filter exits 0 (all reported errors are in `mypy-baseline.txt`). Record the summary line. Task 5 compares against it.

- [ ] **Step 3: Read the file you are about to change**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
cat src/tr_shared/contracts/s2s/listing_internal.py
```

It is 74 lines: a module docstring, `BASE_PATH`, six path builders, and five models. Task 2 replaces it in full.

- [ ] **Step 4: Prove nothing imports `BASE_PATH` by name**

Task 2 renames it. Confirm that is safe across all three consumer repos.

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend
grep -rn "listing_internal import BASE_PATH\|listing_internal\.BASE_PATH" \
  tr-crm-core tr-content-platform tr-lead-management 2>/dev/null | grep -v Binary
```

Expected: **no output** (exit 1). The consumers import only the builder functions and the models; `tr-crm-core/app/modules/admin/clients/listing_client.py:14` keeps its own hardcoded copy of the string, which Plan 2 deletes.

If this produces output, stop and report — the rename would break a caller and needs a coordinated edit.

- [ ] **Step 5: Append the failing tests**

Add to the end of `tests/contracts/s2s/test_listing_internal.py`:

```python
def test_internal_root_and_resource_prefixes():
    assert c.INTERNAL_ROOT == "/api/v1/listing/internal"
    assert c.LISTINGS_BASE_PATH == "/api/v1/listing/internal/listings"
    assert c.PORTAL_PUBLICATIONS_BASE_PATH == "/api/v1/listing/internal/portal-publications"


def test_existing_listing_paths_unchanged_after_prefix_split():
    assert c.by_reference("REF-1") == "/api/v1/listing/internal/listings/by-reference/REF-1"
    assert c.active_count() == "/api/v1/listing/internal/listings/active-count"
    assert c.by_agent("abc") == "/api/v1/listing/internal/listings/by-agent/abc"
    assert c.leads_increment("xyz") == "/api/v1/listing/internal/listings/xyz/leads:increment"
    assert c.access_check("xyz") == "/api/v1/listing/internal/listings/xyz/access-check"


def test_recent_sync_activity_path():
    assert (
        c.recent_sync_activity()
        == "/api/v1/listing/internal/portal-publications/recent-sync-activity"
    )


def test_portal_sync_status_values_match_the_db_check_constraint():
    """These six are CHECK-constrained on
    listing_schema.listing_portal_publications.portal_sync_status. Changing this
    set without a forward migration in tr-content-platform breaks writes."""
    assert {s.value for s in c.PortalSyncStatus} == {
        "pending",
        "syncing",
        "synced",
        "error",
        "disabled",
        "action_required",
    }


def test_activity_row_coerces_sync_status_to_enum():
    row = c.PortalSyncActivityRow.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "portal_name": "propertyfinder",
            "portal_sync_status": "action_required",
            "portal_sync_error": None,
            "last_synced_at": None,
            "portal_listing_status": None,
            "enabled": True,
        }
    )
    assert row.portal_sync_status is c.PortalSyncStatus.ACTION_REQUIRED
    assert row.portal_sync_error is None
    assert row.last_synced_at is None
    assert row.portal_listing_status is None


def test_activity_row_rejects_out_of_vocab_sync_status():
    with pytest.raises(ValidationError):
        c.PortalSyncActivityRow.model_validate(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "portal_name": "propertyfinder",
                "portal_sync_status": "success",
                "enabled": True,
            }
        )


def test_activity_row_ignores_extra_provider_fields():
    row = c.PortalSyncActivityRow.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "portal_name": "bayut",
            "portal_sync_status": "synced",
            "portal_sync_error": None,
            "last_synced_at": "2026-07-24T10:00:00Z",
            "portal_listing_status": "live",
            "enabled": True,
            "pf_quality_score_value": "88.50",
        }
    )
    assert row.portal_sync_status is c.PortalSyncStatus.SYNCED


def test_activity_page_shape():
    page = c.PortalSyncActivityPage.model_validate({"activities": [], "total_count": 0})
    assert page.activities == []
    assert page.total_count == 0


def test_activity_row_rejects_missing_nullable_field():
    """Omitting a nullable-but-required field must raise — this is what turns a
    provider-side column rename into a hard error instead of a silently blank column."""
    with pytest.raises(ValidationError):
        c.PortalSyncActivityRow.model_validate(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "portal_name": "propertyfinder",
                "portal_sync_status": "synced",
                "last_synced_at": None,
                "portal_listing_status": None,
                "enabled": True,
            }
        )


def test_activity_query_defaults():
    q = c.PortalSyncActivityQuery()
    assert q.limit == 20
    assert q.hours_back == 24
    assert q.portal_name is None
    assert q.sync_status is None


def test_activity_query_bounds():
    for limit in (0, 101):
        with pytest.raises(ValidationError):
            c.PortalSyncActivityQuery(limit=limit)
    for hours_back in (0, 169):
        with pytest.raises(ValidationError):
            c.PortalSyncActivityQuery(hours_back=hours_back)
    assert c.PortalSyncActivityQuery(limit=100, hours_back=168).limit == 100


def test_activity_query_sync_status_uses_the_shared_vocabulary():
    """The consumer previously validated this against its own
    success/failed/pending enum, which matched zero rows. Those values must now
    be rejected at the contract boundary."""
    q = c.PortalSyncActivityQuery(sync_status="action_required")
    assert q.sync_status is c.PortalSyncStatus.ACTION_REQUIRED
    with pytest.raises(ValidationError):
        c.PortalSyncActivityQuery(sync_status="success")


def test_activity_query_forbids_unknown_keys():
    """extra='forbid' is what turns a drifted param name into a 422 instead of
    an HTTP 200 with the filter silently ignored."""
    with pytest.raises(ValidationError):
        c.PortalSyncActivityQuery.model_validate({"status_filter": "synced"})


def test_activity_query_serializes_to_wire_params():
    q = c.PortalSyncActivityQuery(portal_name="bayut", sync_status=c.PortalSyncStatus.ERROR)
    assert q.model_dump(mode="json", exclude_none=True) == {
        "portal_name": "bayut",
        "sync_status": "error",
        "limit": 20,
        "hours_back": 24,
    }
```

The file already has `import pytest`, `from pydantic import ValidationError`, `from uuid import uuid4`, and `from tr_shared.contracts.s2s import listing_internal as c` at the top — no import changes needed.

- [ ] **Step 6: Run them and confirm they fail for the right reason**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
.venv/bin/python -m pytest tests/contracts/s2s/test_listing_internal.py -o "addopts=" -q 2>&1 | tail -20
```

Expected: **`4 passed, 13 failed`**.

- The 3 pre-existing tests pass.
- `test_existing_listing_paths_unchanged_after_prefix_split` passes **now and after Task 2** — it touches only existing builders, and pinning it on both sides of the rename is the entire reason it exists.
- The other 13 new tests fail with `AttributeError: module 'tr_shared.contracts.s2s.listing_internal' has no attribute '...'`.

If any new test fails with a *different* error, the test itself is wrong. Fix the test, not the source.

---

## Task 2: Implement the contract

**Files:**
- Modify: `src/tr_shared/contracts/s2s/listing_internal.py` (full rewrite, 74 → ~135 lines)

**Interfaces:**
- Consumes: nothing (stdlib + pydantic only).
- Produces, for Plan 2 in both consumer repos:
  - `INTERNAL_ROOT: str`, `LISTINGS_BASE_PATH: str`, `PORTAL_PUBLICATIONS_BASE_PATH: str`
  - `recent_sync_activity() -> str`
  - `PortalSyncStatus(StrEnum)` — members `PENDING`, `SYNCING`, `SYNCED`, `ERROR`, `DISABLED`, `ACTION_REQUIRED`
  - `PortalSyncActivityRow(BaseModel)` — `id: UUID`, `portal_name: str`, `portal_sync_status: PortalSyncStatus`, `portal_sync_error: str | None`, `last_synced_at: datetime | None`, `portal_listing_status: str | None`, `enabled: bool`
  - `PortalSyncActivityPage(BaseModel)` — `activities: list[PortalSyncActivityRow]`, `total_count: int`
  - All six pre-existing builders and all five pre-existing models, unchanged in behaviour.

- [ ] **Step 1: Replace the file**

Write `src/tr_shared/contracts/s2s/listing_internal.py` in full:

```python
"""S2S contract: tr-content-platform ``/api/v1/listing/internal``.
Callers: tr-lead-management, tr-crm-core.

Two resources share the provider root:

- ``/listings`` — listing reads and the lead-count write.
- ``/portal-publications`` — per-portal sync state
  (``listing_schema.listing_portal_publications``).

``recent_sync_activity`` is fully specified here — path, query, and response —
so callers never hand-build any part of it.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

INTERNAL_ROOT = "/api/v1/listing/internal"
LISTINGS_BASE_PATH = f"{INTERNAL_ROOT}/listings"
PORTAL_PUBLICATIONS_BASE_PATH = f"{INTERNAL_ROOT}/portal-publications"


def by_reference(reference_number: str) -> str:
    return f"{LISTINGS_BASE_PATH}/by-reference/{reference_number}"


def active_count() -> str:
    return f"{LISTINGS_BASE_PATH}/active-count"


def by_agent(agent_id: UUID | str) -> str:
    return f"{LISTINGS_BASE_PATH}/by-agent/{agent_id}"


def leads_increment(listing_id: UUID | str) -> str:
    return f"{LISTINGS_BASE_PATH}/{listing_id}/leads:increment"


def access_check(listing_id: UUID | str) -> str:
    return f"{LISTINGS_BASE_PATH}/{listing_id}/access-check"


def agent_listing_counts_batch() -> str:
    return f"{LISTINGS_BASE_PATH}/agents:batch-count"


def recent_sync_activity() -> str:
    return f"{PORTAL_PUBLICATIONS_BASE_PATH}/recent-sync-activity"


class PortalSyncStatus(StrEnum):
    """Sync state of one listing↔portal publication row.

    Owned by tr-content-platform: it is the CHECK-constrained vocabulary of
    ``listing_schema.listing_portal_publications.portal_sync_status``
    (``ck_listing_portal_publications_portal_sync_status``). Declared here
    because tr-crm-core filters and renders these values over the
    ``recent_sync_activity`` contract below, and previously kept its own
    disagreeing copy (``success``/``failed``/``pending``) — which silently
    matched zero rows on filter and never matched a description key.

    Adding or removing a member requires a forward migration in
    tr-content-platform that regenerates the CHECK constraint.
    """

    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"
    DISABLED = "disabled"
    ACTION_REQUIRED = "action_required"


class ListingInternalRef(BaseModel):
    """Lean S2S view; extra='ignore' lets provider add fields without breaking callers.
    Provider superset drift is guarded by a contract test."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    reference_number: str | None = None
    listing_status: str
    title_en: str | None = None
    tenant_id: UUID
    leads_count: int = 0
    last_lead_at: datetime | None = None
    # JSONB dicts in the DB: {"id": ..., "name": ...}
    listing_owner: dict | None = None
    listing_agent: dict | None = None


class ListingLeadCountOut(BaseModel):
    listing_id: UUID
    leads_count: int
    last_lead_at: datetime | None = None


class ListingActiveCountOut(BaseModel):
    count: int


class AgentListingCountsRequest(BaseModel):
    tenant_id: UUID
    agent_ids: list[UUID] = Field(..., max_length=500)


class AgentListingCountRow(BaseModel):
    agent_id: UUID
    listings_count: int


class AgentListingCountsResponse(BaseModel):
    rows: list[AgentListingCountRow]


class PortalSyncActivityQuery(BaseModel):
    """Query vocabulary for ``recent_sync_activity()``.

    Both sides declare these here and nowhere else: the provider takes it as
    ``Annotated[PortalSyncActivityQuery, Query()]``, the consumer sends
    ``model_dump(mode="json", exclude_none=True)``. A key that drifts on one
    side is then a 422, not an HTTP 200 with the filter silently ignored.

    ``extra="forbid"`` is deliberate and is the opposite of
    ``PortalSyncActivityRow``'s ``extra="ignore"``. A response may legitimately
    grow fields an older caller does not know; a request may not — an
    unrecognised query key means the caller believes it is filtering when it is
    not, so it must fail loudly.

    Defaults belong here for the same reason the bounds do: they are the
    contract. Note this is the reverse of ``PortalSyncActivityRow``, whose
    nullable fields carry no default — there, absent means provider drift; here,
    absent means "caller did not ask", which has a defined answer.
    """

    model_config = ConfigDict(extra="forbid")

    portal_name: str | None = None
    sync_status: PortalSyncStatus | None = None
    limit: int = Field(20, ge=1, le=100)
    hours_back: int = Field(24, ge=1, le=168)


class PortalSyncActivityRow(BaseModel):
    """One publication row as the monitoring caller reads it.

    ``portal_name`` stays ``str`` deliberately. The canonical typed vocabulary is
    ``tr_shared.integrations.PortalSlug``, but ``tr_shared.integrations``'s package
    ``__init__`` imports ``config_client`` → ``httpx``, and ``contracts/`` is a
    declarations-only package with no runtime dependencies beyond pydantic.
    Importing it here would couple every contract consumer to an optional extra.
    The producer's DB CHECK already constrains this column to the four listing
    portal slugs.

    ``portal_sync_error``, ``last_synced_at`` and ``portal_listing_status`` carry
    no default: they are required-but-nullable, so an explicit ``null`` still
    validates but a missing key raises — a renamed field is a type error, not a
    silent ``None``.
    """

    model_config = ConfigDict(extra="ignore")

    id: UUID
    portal_name: str
    portal_sync_status: PortalSyncStatus
    portal_sync_error: str | None
    last_synced_at: datetime | None
    portal_listing_status: str | None
    enabled: bool


class PortalSyncActivityPage(BaseModel):
    activities: list[PortalSyncActivityRow]
    total_count: int
```

- [ ] **Step 2: Run the contract tests**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
.venv/bin/python -m pytest tests/contracts/s2s/test_listing_internal.py -o "addopts=" -q 2>&1 | tail -5
```

Expected: `17 passed`. (11 as first drafted, +1 from the final-review fix wave, +5 for `PortalSyncActivityQuery`.)

- [ ] **Step 3: Run the whole contracts suite for regressions**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
.venv/bin/python -m pytest tests/contracts -o "addopts=" -q 2>&1 | tail -5
```

Expected: `45 passed` (31 baseline + 14 added here). Zero failures.

- [ ] **Step 4: Prove the layering rule holds**

`contracts/` must stay importable with only pydantic installed. Confirm the new module pulls in nothing from `tr_shared.integrations`, `tr_shared.http`, or `tr_shared.db`:

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
.venv/bin/python - <<'EOF'
import sys
for mod in list(sys.modules):
    if mod.startswith("tr_shared"):
        del sys.modules[mod]

import tr_shared.contracts.s2s.listing_internal  # noqa: F401

leaked = sorted(
    m for m in sys.modules
    if m.startswith("tr_shared.")
    and not m.startswith("tr_shared.contracts")
)
print("leaked tr_shared modules:", leaked)
assert not leaked, leaked
print("OK — contracts layer is self-contained")
EOF
```

Expected:
```
leaked tr_shared modules: []
OK — contracts layer is self-contained
```

If this fails, an import crept in. Remove it — do not relax the assertion.

- [ ] **Step 5: Run the mypy ratchet**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
set +o pipefail
.venv/bin/mypy src/tr_shared/ | .venv/bin/mypy-baseline filter 2>&1 | tail -10
```

Expected: same result as Task 1 Step 2 — zero *new* errors. Do not touch `mypy-baseline.txt`.

---

## Task 3: Version bump and changelog

**Files:**
- Modify: `pyproject.toml:3`
- Modify: `CHANGELOG.md` (insert at top of the entry list)

**Interfaces:**
- Consumes: the symbols added in Task 2.
- Produces: `tr-shared-lib==0.40.0`, the version both consumer repos will pin their floor to in Plan 2.

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change line 3:

```toml
version = "0.39.0"
```

to:

```toml
version = "0.40.0"
```

- [ ] **Step 2: Add the changelog entry**

`CHANGELOG.md` currently opens with `## [0.33.0] - 2026-07-15` at line 8, even though the package is at 0.39.0 — entries for 0.34.0–0.39.0 were never written. **Do not backfill them.** That is unrelated archaeology and out of scope; it is flagged in the "Out of scope" section at the end of this plan.

Insert immediately above line 8 (`## [0.33.0] - 2026-07-15`):

```markdown
## [0.40.0] - 2026-07-24

### Added
- `contracts.s2s.listing_internal.PortalSyncStatus` — SSOT for
  `listing_schema.listing_portal_publications.portal_sync_status`
  (`pending`/`syncing`/`synced`/`error`/`disabled`/`action_required`), the
  CHECK-constrained vocabulary owned by tr-content-platform. tr-crm-core
  previously declared its own disagreeing copy (`RecentSyncStatus` =
  `success`/`failed`/`pending`), which made `status_filter=success|failed`
  match zero rows and made every sync-activity description fall through to the
  `"Sync pending"` fallback. Both are fixed by both sides importing this.
- `contracts.s2s.listing_internal.recent_sync_activity()` path builder plus
  `PortalSyncActivityRow` / `PortalSyncActivityPage` response models — the S2S
  contract that replaces tr-crm-core's cross-schema raw SQL read of
  `public.listing_portal_publications`.
- `contracts.s2s.listing_internal.PORTAL_PUBLICATIONS_BASE_PATH` — second
  resource prefix under the same provider root.
- CI now runs `tests/contracts` (it previously ran only the event-bus suites, so
  no S2S contract test was gated).

### Changed
- `contracts.s2s.listing_internal.BASE_PATH` split into `INTERNAL_ROOT` +
  `LISTINGS_BASE_PATH` + `PORTAL_PUBLICATIONS_BASE_PATH`. A bare `BASE_PATH`
  became ambiguous once the module carried two resources. No caller imported the
  old name (verified across tr-crm-core, tr-content-platform,
  tr-lead-management); every emitted path is byte-identical, pinned by
  `test_existing_listing_paths_unchanged_after_prefix_split`.
```

- [ ] **Step 3: Verify the version parity guard still passes**

`tests/test_version_parity.py` asserts `tr_shared.__version__ == pyproject["project"]["version"]`. `__version__` is read from **installed package metadata** (`src/tr_shared/__init__.py:9`), not from the source tree — so it will not see 0.40.0 until the venv is reinstalled.

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
uv sync --reinstall-package tr-shared-lib
.venv/bin/python -m pytest tests/test_version_parity.py -o "addopts=" -q 2>&1 | tail -5
```

Expected: `2 passed`.

If you skip the reinstall, this test fails with `AssertionError: '0.39.0' != '0.40.0'` — that is the reinstall being missing, not a code bug.

---

## Task 4: Put the contract tests under CI

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the tests from Tasks 1–2.
- Produces: a CI gate that fails when a contract drifts.

The `test` job currently runs a hand-picked scope (comment in the file: *"Scoped to event-bus consumer suite — full suite has pre-existing failures in unrelated modules"*). `tests/contracts` is not in it — so the S2S contract tests, including the ones this plan just added, never run in CI. Adding the directory is safe: it is 39 tests, all passing, ~0.15s, zero external services.

- [ ] **Step 1: Confirm the suite is green and fast in isolation**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
.venv/bin/python -m pytest tests/contracts -o "addopts=" -q --durations=3 2>&1 | tail -8
```

Expected: `45 passed`, total wall time well under 1s, no test over 0.05s.

- [ ] **Step 2: Extend the CI pytest scope**

In `.github/workflows/ci.yml`, in the `test` job's final step, change:

```yaml
        run: >-
          uv run pytest
          tests/unit/events tests/integration
          tests/test_consumer.py tests/test_version_parity.py
          --no-cov
```

to:

```yaml
        run: >-
          uv run pytest
          tests/unit/events tests/integration tests/contracts
          tests/test_consumer.py tests/test_version_parity.py
          --no-cov
```

- [ ] **Step 3: Reproduce the exact CI invocation locally**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
.venv/bin/python -m pytest \
  tests/unit/events tests/integration tests/contracts \
  tests/test_consumer.py tests/test_version_parity.py \
  --no-cov -q 2>&1 | tail -8
```

Expected: all passed, zero failures. Redis-backed `@pytest.mark.integration` tests skip locally without `TEST_REDIS_URL` — skips are fine, failures are not.

---

## Task 5: Final verification and handoff

**Files:** none modified.

**Interfaces:**
- Consumes: everything above.
- Produces: the go/no-go signal for Plan 2.

- [ ] **Step 1: Full verification sweep**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib

echo "--- contracts ---"
.venv/bin/python -m pytest tests/contracts -o "addopts=" -q 2>&1 | tail -3

echo "--- version parity ---"
.venv/bin/python -m pytest tests/test_version_parity.py -o "addopts=" -q 2>&1 | tail -3

echo "--- mypy ratchet ---"
set +o pipefail
.venv/bin/mypy src/tr_shared/ | .venv/bin/mypy-baseline filter 2>&1 | tail -3

echo "--- version ---"
grep '^version' pyproject.toml
```

Expected: `45 passed`, `2 passed`, mypy filter clean (no new errors), `version = "0.40.0"`.

- [ ] **Step 2: Confirm the changed-file set**

```bash
cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-shared-lib
git status --porcelain
```

Expected, ignoring pre-existing unrelated `plans/` entries:
```
 M .github/workflows/ci.yml
 M pyproject.toml
 M src/tr_shared/contracts/s2s/listing_internal.py
 M tests/contracts/s2s/test_listing_internal.py
 M uv.lock
```

Two entries need explaining, because an earlier draft of this plan got both wrong:

- **`uv.lock` is expected and must be kept.** This repo is its own root package, so the lock records `tr-shared-lib`'s own version. Task 3's bump makes the lock's `version = "0.39.0"` stale, and `uv sync --reinstall-package` rewrites exactly that one line. CI runs `uv sync --locked`, which fails hard when the lock disagrees with `pyproject.toml`. Verify the diff is the single-line self-version bump and nothing else:
  ```bash
  git diff --stat -- uv.lock   # expect: 1 file changed, 1 insertion(+), 1 deletion(-)
  ```
- **`CHANGELOG.md` will NOT appear.** It is gitignored in this repo (`.gitignore:68`). The 0.40.0 entry is still written — it is just local-only and never reaches GitHub. See "Out of scope" for the open question that raises.

`mypy-baseline.txt` must not appear. If it does, revert it — never regenerate the baseline to absorb a new error.

**Read-only command.** Do not run any other git command. No `add`, no `commit`, no `push`.

- [ ] **Step 3: Hand off to the user**

Report, verbatim structure:

> **`tr-shared-lib` 0.40.0 ready — not pushed.**
>
> Five files changed:
> - `src/tr_shared/contracts/s2s/listing_internal.py` — `PortalSyncStatus`, `recent_sync_activity()`, `PortalSyncActivityQuery`, `PortalSyncActivityRow`, `PortalSyncActivityPage`, prefix split
> - `tests/contracts/s2s/test_listing_internal.py` — 14 new tests
> - `pyproject.toml` — 0.39.0 → 0.40.0
> - `CHANGELOG.md` — 0.40.0 entry
> - `.github/workflows/ci.yml` — `tests/contracts` now gated
>
> Verified: 45 contract tests pass, version parity passes, mypy ratchet clean, contracts layer proven dependency-free.
>
> **Your steps:**
> 1. Review and push `tr-shared-lib`.
> 2. Re-lock in **both** consumers:
>    ```bash
>    cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-content-platform
>    uv lock --upgrade-package tr-shared-lib
>    uv sync --frozen --reinstall-package tr-shared-lib
>
>    cd /Users/ehtishamsadiq/Data/TR/prod/Backend/tr-crm-core
>    uv lock --upgrade-package tr-shared-lib
>    uv sync --frozen --reinstall-package tr-shared-lib
>    ```
> 3. Tell me when done — Plan 2 starts with a gate that verifies the symbols are importable in both repos.

- [ ] **Step 4: Stop**

Do not start Plan 2. It is blocked until the user confirms the push and re-lock.

---

## Out of scope — flagged, not fixed

Named here so they are not silently absorbed, per the Surgical Changes rule.

| Thing | Where | Why not now |
|---|---|---|
| `CHANGELOG.md` missing 0.34.0–0.39.0 | `CHANGELOG.md:8` — top entry is 0.33.0 while the package is 0.39.0 | Six releases of archaeology across unrelated features. Needs its own pass over the git log. |
| `CHANGELOG.md` is gitignored | `.gitignore:68` | Discovered during Task 3. The file is never committed, so no consumer or reviewer can read the release notes — which is also why six releases of entries went missing unnoticed. Un-ignoring it is a repo-policy decision (and would make the 0.34.0–0.39.0 gap publicly visible), so it belongs to the user, not to this plan. The 0.40.0 entry is written either way. |
| CI `test` job runs a hand-picked scope | `.github/workflows/ci.yml` | The comment says the full suite has pre-existing failures in `tests/unit/celery` and `tests/unit/integrations/pf`. Fixing those is its own ticket. This plan adds one known-green directory and no more. |
| `contracts/s2s/__init__.py` re-exports only `access_check` | `src/tr_shared/contracts/s2s/__init__.py:20` | Consistent as-is: every other module is imported by full path. Making it exhaustive would create two import paths per symbol. |
| `tr-crm-core` and `tr-lead-management` duplicate `BASE_PATH` as a client class attribute | e.g. `tr-crm-core/.../clients/listing_client.py:14` | Real SSOT violation. Plan 2 fixes it for `listing_client.py` because that file is being rewritten there anyway. `lead_client.py` and `wam_client.py` are untouched by either plan. |
