# listing — Soft-Delete COLUMN SSOT Cleanup (Plan v1)

**Date:** 2026-07-20 (re-scoped 2026-07-23 after audit)
**Service:** `tr-content-platform` (listing module)
**Status:** Task A (admin) — **DONE**, shipped 2026-07-20 in commit `67ed103`. Task L (listing) — **PENDING**, verified still unfixed 2026-07-23.
**Relation:** follow-up to the soft-delete **method** relocation work (now shipped). This handles the remaining **column-level** soft-delete duplication in the listing module. Independent — the columns already live on `SoftDeleteMixin` today, so no shared-lib version bump is needed.
**Shared-lib impact:** NONE. Service-local. No `tr-shared-lib`/`shared-auth-lib` change.

---

## 0. Scope & honesty boundary

Removes duplicated soft-delete **columns** (`deleted_at`, `is_active`) from listing models — verified DDL-neutral. Deliberately does **not**:
- touch auth `is_deleted` or Employee's override (converging those is wrong/breaking);
- converge listing's **timestamp/audit** column duplication (larger, separate effort — see §3 Flag). One concern per plan (KISS).

Zero-DDL (columns identical before/after) → **no migration**. Gated on an `autogenerate`/`migrate check` producing an EMPTY diff; if any diff appears, STOP and report.

---

## Task A — admin: drop redundant local `SoftDeleteMixin` — ✅ DONE

Shipped 2026-07-20, commit `67ed103` ("refactor(crm-core): align admin soft delete mixins with shared base update"). The local `admin` `SoftDeleteMixin` was deleted from `mixins.py`, `FollowUpRule` re-based to `class FollowUpRule(BaseModel, TenantMixin, AuditMixin)`, and the import trimmed. Admin `BaseModel` still carries its own `deleted_at`/`is_active` (with `comment=`) — unchanged, zero-DDL. No open work. Section retained only as the audit-trail pointer to `67ed103`.

---

## Task L — listing: extract the 8× duplicated soft-delete column pair — ⏳ PENDING

### Evidence (live, re-verified 2026-07-23)
**8 listing models** inline the identical soft-delete pair (paths under `app/modules/listing/models/listing/`):
`listing.py:245,255`, `listing_permit.py:86,95`, `listing_portal_publication.py:131,140`, `listing_media.py:92,101`, `listing_status_history.py:76,85`, `listing_pricing.py:135,144`, `listing_portal_field.py:73,82`, `listing_document.py:69,78`.

Zero `SoftDeleteMixin` references exist in the listing module today — the duplication is unfixed.

Every occurrence is byte-identical AND identical to tr_shared's `SoftDeleteMixin` (`tr-shared-lib/src/tr_shared/db/base.py:57-62`):
```python
deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
is_active: Mapped[bool] = mapped_column(Boolean, server_default=sqltext("true"), nullable=False)
```
- No `index=`/`comment=` on these two columns → **DDL-identical to tr_shared's mixin** (tr_shared uses `text("true")`, listing uses the `sqltext` import alias — same DDL).
- listing's `Base = (AsyncAttrs, DeclarativeBase)` (`app/core/database.py:33`) is 2.0-native → tr_shared's `mapped_column`-based mixin applies cleanly (proven: HR does this already).
- `__table_args__` indexes (e.g. `Index(..., "is_active")`) reference the column **by name** and are unaffected by where it's declared — they stay in each model. Safe.

### Change — adopt tr_shared `SoftDeleteMixin` (the real cross-service SSOT)
For each of the 8 models:
1. Delete the inline `deleted_at` + `is_active` `mapped_column` lines.
2. Add `SoftDeleteMixin` to the class bases: `class Listing(SoftDeleteMixin, Base):` (mixin first so its columns compose onto `Base`'s metadata = `listing_schema`).
3. Import: `from tr_shared.db import SoftDeleteMixin`.
4. Remove now-orphaned imports per file (`Boolean` / `sqltext` if this pair was their only use — verify per file; many models use `Boolean`/`sqltext` elsewhere).

- **DDL-neutral:** columns are identical; they just come from the mixin now. Verify via autogenerate.
- **Additive bonus:** the 8 models gain `soft_delete()`/`restore()` instance methods (present on the mixin). NOT required for this task — listing soft-deletes via repository UPDATE today; methods just become available.

**Why tr_shared mixin, not a local `ListingSoftDeleteMixin`:** these columns are exactly tr_shared's — a local mixin would reinvent the platform SSOT. Direct adoption is the permanent fix.

### Verify (in `tr-content-platform`)
```bash
cd tr-content-platform
uv run alembic -c app/modules/listing/alembic.ini revision --autogenerate -m _probe  # MUST be empty → delete probe
uv run pytest tests/listing -q
uv run ruff check app/modules/listing/
```
- **Gate:** empty autogenerate diff across ALL 8 tables (proves no column drift), listing tests green. If ANY table shows a `deleted_at`/`is_active` diff, STOP — that model's inline decl wasn't identical; report it.

---

## 3. Flag — NOT in this plan (larger, separate)

**A. listing `metrics/` models also inline the soft-delete pair — but WITH an index.**
`metrics_daily.py:73,76`, `metrics_hourly.py:78,81`, `request_log.py:69,72` inline `deleted_at`/`is_active` too, but carry `Index(..., "deleted_at")` → **NOT DDL-identical** to the bare mixin. Outside Task L's 8-model scope. Do NOT fold these into Task L (adopting the plain mixin would drop their index → a migration). Track separately; listing soft-delete cleanup is NOT "done" after only the 8 models.

**B. listing also duplicates timestamp + audit columns inline** across the same 8 models (`created_at`/`updated_at`/`created_by`/`updated_by`), with `func.current_timestamp()` vs tr_shared's `func.now()`. Converging those forces a DDL default migration or a listing-local timestamp mixin — a bigger "listing shared base" refactor. Separate plan (`listing-common-columns-base-ssot`). Decide AFTER this soft-delete pass lands.

---

## 4. Execution & done-bar

- Task L is behavior-preserving, zero-DDL.
- Done-bar: empty autogenerate diff across all 8 tables · listing tests green · ruff clean · zero remaining inline `deleted_at`/`is_active` in the 8 models.
- **Git:** none by me. You commit. Neither task needs a shared-lib relock — service-local.

---

## 5. What I need from you

1. **Approve Task L** (listing → tr_shared `SoftDeleteMixin`, soft-delete columns only, the 8 models).
2. **§3-A metrics models** — separate follow-up (they have an index; can't use bare mixin), or leave as-is? (Rec: separate — decide after Task L.)
3. **§3-B timestamp/audit convergence** — separate plan later, or leave listing's non-soft-delete columns as-is? (Rec: separate plan.)

On approval I execute Task L, verify, report the autogenerate diff at the gate.
