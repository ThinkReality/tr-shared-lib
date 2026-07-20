# tr-shared-lib — Relocate `soft_delete()`/`restore()` onto `SoftDeleteMixin` (Plan v1)

**Date:** 2026-07-20
**Library:** `tr-shared-lib` (`src/tr_shared/db/base.py`)
**Version:** `0.35.0` → **`0.36.0`** (minor — additive, behavior-preserving)
**Status:** PLAN — awaiting your approval. No code written. No git ops.
**Trigger:** scraping-module SSOT cleanup (D1). Fleet blast-radius was mapped live across all 8 services before writing this — see §2.

---

## 1. What changes and why

Today (`db/base.py`):
- `SoftDeleteMixin` (line 54) declares **columns only** (`deleted_at`, `is_active`).
- `soft_delete()` / `restore()` (lines 76-82) live on **`BaseModel`**, not the mixin.

That placement is wrong: the methods operate purely on the mixin's own columns, so they belong on the mixin. Because they sit on `BaseModel`, any model that wants the columns **without** the full `BaseModel` (schema-isolated modules with their own `Base`, or tables without `tenant_id`) must **re-declare the two methods by hand**. That has produced **3 duplicate copies** across the fleet (scraping, HR, task).

**The fix:** move `soft_delete()` / `restore()` down onto `SoftDeleteMixin`. `BaseModel` still inherits `SoftDeleteMixin`, so every existing `BaseModel` subclass resolves the methods through the identical MRO — **no behavior change**. Models that inherit the mixin directly now get the methods for free, letting the 3 duplicates be deleted.

This is a genuine SSOT correction to the library itself, not churn for one service.

---

## 2. Blast radius — verified live across the fleet (why this is safe)

`SoftDeleteMixin` is in the model MRO of **5 services**. Each was read to confirm the move is additive/no-op:

| Service / module | Uses | Effect of the move |
|---|---|---|
| tr-media-service (MediaFile, OCRExtraction) | tr_shared `BaseModel` | no-op (methods via same MRO) |
| tr-people-finance / finance | tr_shared `BaseModel` | no-op |
| tr-people-finance / hr | local `Base` + `HRSoftDeleteMixin(SoftDeleteMixin)` + **dup methods** | no-op **+ unlocks deleting `HRSoftDeleteMixin`** |
| tr-lead-management | local `BaseModel(tr_shared BaseModel)` | no-op |
| tr-crm-core / activity, notification, learning | tr_shared `BaseModel` | no-op |
| tr-crm-core / task | local `BaseModel(…, SoftDeleteMixin, …)` + **dup methods** | no-op **+ unlocks deleting dup methods** |
| tr-content-platform / cms | `TenantedModel = tr_shared BaseModel` | no-op |

**Structurally immune / untouched (do NOT inherit tr_shared `SoftDeleteMixin`):**
- tr-crm-core / **auth** — uses `is_deleted` (own ADR); never inherits the mixin → the relocated `is_active=False` method can never land on an auth model. **Confirmed safe.**
- tr-crm-core / **admin** — local `Base` + local `SoftDeleteMixin`. Untouched.
- tr-content-platform / **listing** — custom `Base`, hand-declared columns. Untouched.
- tr-people-finance / **Employee** — deliberate override (`deleted_at`-only, keeps `is_active` as employment state). Its class-level methods still win by MRO. **Confirmed safe.**
- tr-api-gateway, tr-whatsApp-marketing-agent, shared-auth-lib — no models using the mixin.

**MRO safety proof:** the move only *adds* methods to `SoftDeleteMixin`. Every consumer either (a) already reached them via `BaseModel → SoftDeleteMixin` (unchanged resolution), or (b) defines its own copy on a more-derived class (task, HR, Employee), which continues to win by Python MRO. No model gains a wrong-semantics method; no diamond forms (HR/scraping/task use separate `declarative_base` registries).

**Proven pattern:** HR **already** applies tr_shared's `mapped_column`-based `SoftDeleteMixin` to a legacy `declarative_base()` model today (`HRSoftDeleteMixin(SoftDeleteMixin)`) and works — so scraping adopting the same mixin on its legacy `Base` is a known-good pattern, not a new risk.

---

## 3. Execution — two gated phases

**Phase 1 = tr-shared-lib only.** I write it, you push + relock. **Phase 2 = the 3 consumer cleanups**, each done ONLY after you confirm that service has relocked `tr-shared-lib>=0.36.0`. Phase 2 code cannot land before Phase 1 is locked (HR/task would lose their methods otherwise).

---

## PHASE 1 — `tr-shared-lib` (I write; you push + relock)

### Step 1.1 — `src/tr_shared/db/base.py`

Move the two methods from `BaseModel` onto `SoftDeleteMixin`. Exact result:

```python
class SoftDeleteMixin:
    """Never hard-DELETE rows — soft-delete only."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
        self.is_active = False

    def restore(self) -> None:
        self.deleted_at = None
        self.is_active = True


class BaseModel(Base, TimestampMixin, TenantMixin, AuditMixin, SoftDeleteMixin):
    """Inherit this, not Base — adds id plus every mixin column."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id})>"
```

- Method bodies copied verbatim (identical `datetime.now(timezone.utc)` semantics). `datetime`/`timezone` already imported at top (line 5) — no import change.
- `__repr__` stays on `BaseModel` (it uses `self.id`, which is a `BaseModel` concern, not a soft-delete one). Correct separation.
- No column change → **no migration in any service**.

### Step 1.2 — `db/__init__.py`

**No change.** `SoftDeleteMixin` is already exported (line 7 + `__all__` line 45). Consumers can already `from tr_shared.db import SoftDeleteMixin`.

### Step 1.3 — Tests: `tests/unit/db/test_base.py`

Existing `TestSoftDelete` / `TestRestore` call the methods through `SampleModel(BaseModel)` — still pass (BaseModel still inherits them). **Add** direct-mixin coverage so the relocation is pinned as the SSOT contract (guards against a future revert putting them back on BaseModel):

```python
class TestSoftDeleteMixinMethods:
    """Methods live on the mixin itself, not only on BaseModel —
    so schema-isolated models inheriting the mixin directly get them."""

    def test_mixin_has_soft_delete(self):
        assert hasattr(SoftDeleteMixin, "soft_delete")

    def test_mixin_has_restore(self):
        assert hasattr(SoftDeleteMixin, "restore")

    def test_mixin_soft_delete_sets_fields(self):
        class _M(SoftDeleteMixin):
            pass
        m = _M()
        m.soft_delete()
        assert m.is_active is False
        assert m.deleted_at is not None

    def test_mixin_restore_clears_fields(self):
        class _M(SoftDeleteMixin):
            pass
        m = _M()
        m.soft_delete()
        m.restore()
        assert m.is_active is True
        assert m.deleted_at is None
```
(The bare `class _M(SoftDeleteMixin)` — no `Base` — instantiates cleanly because on a non-mapped plain class the `mapped_column` descriptors just sit as attributes; the methods set instance attributes. If instantiation fights the mapped descriptors, fall back to asserting `SoftDeleteMixin.soft_delete`/`restore` are callable + reuse the existing `SampleModel` for behavior — the behavior is already covered by `TestSoftDelete`.)

### Step 1.4 — Version bump: `pyproject.toml`

`version = "0.35.0"` → `version = "0.36.0"`. Minor bump: additive, behavior-preserving, no API removal.

### Step 1.5 — Phase-1 verification (I run, in `tr-shared-lib`)

```bash
cd tr-shared-lib
uv run pytest tests/unit/db/test_base.py -q      # all green incl. new mixin tests
uv run pytest -q                                  # full lib suite, no new failures
uv run ruff check src/ tests/                     # clean
uv run mypy src/tr_shared/db/base.py              # clean (disallow_untyped_defs on)
```
Done-bar: full lib suite green, ruff clean, mypy clean.

### Step 1.6 — HANDOFF TO YOU
- I stop. You `git push` tr-shared-lib (0.36.0).
- You relock the **3 Phase-2 services**: `realty-data-hub`, `people-finance`, `tr-crm-core` (`uv lock --upgrade-package tr-shared-lib` in each).
- The other consumers (media, lead, content-platform) need **no relock for correctness** (behavior is unchanged); they pick 0.36.0 up on their next natural lock.
- You tell me each service is relocked → I start that service's Phase-2 cleanup.

---

## PHASE 2 — Consumer cleanups (ONLY after §1.6 relock, per service)

Each deletes a now-redundant duplicate. All zero-DDL (columns already identical), method-source-only. Each independently verifiable.

### 2A — tr-realty-data-hub / scraping (the original D1 target)

**File `app/modules/scraping/db/base.py`** — replace the local mixin with a re-export:
```python
"""Base configuration for SQLAlchemy ORM."""

from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base
from tr_shared.db import SoftDeleteMixin  # noqa: F401  (re-exported for models)

metadata = MetaData(schema="scraped_data")
Base = declarative_base(metadata=metadata)
```
- Deletes local `class SoftDeleteMixin` (columns + `soft_delete`). Removes now-orphaned imports (`Boolean`, `Column`, `DateTime`, `UTC`, `datetime`).
- `models/property.py` + `models/trakheesi.py` keep `from ..db.base import Base, SoftDeleteMixin` **unchanged** (now resolves to the re-exported tr_shared mixin). Their `class Property(SoftDeleteMixin, Base)` MRO is unchanged.
- **Behavior delta:** scraping *gains* `restore()` (local mixin lacked it) — additive, harmless (no caller today). `soft_delete()` semantics identical.
- **Column DDL:** `Column(DateTime(tz=True), nullable=True)` ≡ `mapped_column(DateTime(tz=True), nullable=True)`; `server_default="true"` ≡ `server_default=text("true")` → **identical DDL, no migration.**

**Verify (in `tr-realty-data-hub`):**
```bash
cd tr-realty-data-hub
uv run alembic revision --autogenerate -m _probe   # MUST be empty (no column diff) → delete the probe file
uv run pytest tests/scraping -q                      # incl. tests/scraping/integration/test_alembic_chain.py
uv run ruff check app/modules/scraping/
```
- **Gate:** the autogenerate probe MUST produce an empty migration. If it shows ANY diff on `deleted_at`/`is_active`, STOP — do not proceed, report the diff.
- Update `tests/scraping/integration/test_alembic_chain.py` only if it asserts the local mixin identity (re-read it first).

### 2B — tr-people-finance / hr (delete `HRSoftDeleteMixin`)

**File `app/modules/hr/models/base.py`** — `HRSoftDeleteMixin` exists *solely* because the methods were on `BaseModel` (its own docstring says so). Now redundant. Result:
```python
from sqlalchemy.orm import declarative_base

Base = declarative_base()
```
(Delete `HRSoftDeleteMixin` + its two methods + the now-unused `datetime`/`timezone` imports + the `SoftDeleteMixin` import IF no longer referenced here.)

**Update every HR model** that inherits `HRSoftDeleteMixin` → inherit tr_shared `SoftDeleteMixin` directly. Sites (from live grep):
- `models/attendance/attendance.py:23,56,81,114,254,308` (6 classes) + import line `:20`
- `models/outbox/event_outbox.py:25` + import `:18`
- `models/sync_config/sync_config.py:19` + import `:16` (+ docstring mention `:23`)

Change `from app.modules.hr.models.base import Base, HRSoftDeleteMixin` → `from app.modules.hr.models.base import Base` **and** `from tr_shared.db import SoftDeleteMixin`; class bases `(..., HRSoftDeleteMixin)` → `(..., SoftDeleteMixin)`.
- **Zero column change** (HR already used tr_shared mixin columns via `HRSoftDeleteMixin(SoftDeleteMixin)`). Methods now come from the same mixin. No migration.
- **Employee untouched** (never used `HRSoftDeleteMixin`).

**Verify (in `tr-people-finance`):**
```bash
cd tr-people-finance
make test-db-up
uv run migrate check                    # no pending diff for hr tree
PYTHONPATH=. uv run pytest tests/hr -q  # green (soft_delete/restore still work on HR models)
uv run ruff check app/modules/hr/
```
- **Gate:** `migrate check` clean (no DDL diff). Grep-confirm zero remaining `HRSoftDeleteMixin` references before done.

### 2C — tr-crm-core / task (delete duplicate methods)

**File `app/modules/task/models/base.py`** — delete the local `soft_delete()` (:41) + `restore()` (:47) from the local `BaseModel`; they now come from the inherited tr_shared `SoftDeleteMixin`. Remove the now-unused inline `from datetime import timezone` (:42) and top-level `datetime`/`func` imports **only if** they become orphaned (task's local `TimestampMixin` still uses `func`/`datetime` — verify before removing).
- Local `BaseModel(Base, TimestampMixin, SoftDeleteMixin, AuditMixin)` unchanged in shape; it just stops re-declaring the two methods. `SoftDeleteMixin` already in its bases → methods resolve there. Identical semantics.
- task's local `TimestampMixin` + hand-declared `id`/`tenant_id` are **out of scope** (separate concern; leave).

**Verify (in `tr-crm-core`):**
```bash
cd tr-crm-core
uv run migrate check                       # tasks tree: no diff
uv run pytest tests/task -q                # soft_delete/restore behavior green
uv run ruff check app/modules/task/
```
- **Gate:** `migrate check` clean. Grep-confirm task models still expose `soft_delete`/`restore` (via inheritance) and behavior tests pass.

---

## 4. Out of scope — with honest reasoning

**Scope boundary of THIS plan:** it relocates the two *methods* (`soft_delete`/`restore`) and deletes the 3 duplicate *method* copies that relocation unlocks (scraping, HR, task). It is **zero-DDL / zero-migration**. The items below duplicate soft-delete *columns*, not methods — the method relocation neither unlocks nor requires touching them, and converging columns would turn this into a multi-service migration project (breaks KISS + one-concern-per-plan). They split into two categories:

### 4a. Leave FOREVER — converging is wrong/breaking (not deferred debt)
- **auth `is_deleted`** (`tr-crm-core` auth module) — uses an `is_deleted` boolean, not `is_active`+`deleted_at`. tr-crm-core CLAUDE.md locks it: *"crm-backend deviation stays contained to auth… Do NOT harmonize."* Converging needs a data migration AND fights a documented ADR. Permanent-correct as-is.
- **Employee override** (`tr-people-finance` hr) — `soft_delete()` sets `deleted_at` only; `is_active` deliberately means "currently employed" (business state), documented in people-finance CLAUDE.md. Converging would **break business semantics**. Its class-level methods keep winning by MRO regardless of Phase 1.

### 4b. Genuinely deferred — real column-level DRY debt, own plan required
Not touched here because they need per-model column-parity verification + migrations, which is out of this method-relocation's scope. Tracked in **`admin-listing-softdelete-column-ssot-plan-v1.md`**:
- **listing hand-declared columns** (`tr-content-platform`) — **8 listing models** re-declare the identical `deleted_at`+`is_active` block (`listing`, `listing_permit`, `listing_portal_publication`, `listing_media`, `listing_status_history`, `listing_pricing`, `listing_portal_field`, `listing_document`). Bigger DRY smell than scraping's. `Base` is 2.0-native so a shared mixin applies cleanly — but parity (index/comment/default) is unverified, so a naïve swap could drop an index/comment → migration. Real follow-up.
- **admin local `SoftDeleteMixin`** (`tr-crm-core/app/modules/admin/models/mixins.py`) — admin-INTERNAL dup: admin's `BaseModel` already inlines the two columns, and `FollowUpRule` *additionally* inherits the local `SoftDeleteMixin` that re-declares them (double-declare; only 1 model uses that mixin). Fix is an admin-internal tidy (drop the redundant mixin from `FollowUpRule`), NOT a tr_shared swap; admin's columns also carry `comment=` that tr_shared's mixin lacks. Small, admin-scoped.

---

## 5. Rollback

- Phase 1 is a pure method relocation. Revert = move the two methods back onto `BaseModel`, re-bump. No data/schema involved.
- Phase 2 cleanups are independent; any one can be reverted by restoring its deleted local mixin/methods. No DDL was emitted, so no DB rollback needed.

---

## 6. What I need from you

1. **Approve Phase 1** (the tr-shared-lib change + version bump).
2. On approval: I write §1.1–1.4, run §1.5, and **stop**. You push 0.36.0 + relock the 3 services.
3. Tell me per service when relocked → I execute 2A / 2B / 2C for that service and verify.

No git ops by me anywhere. You push tr-shared-lib and relock every consumer.
