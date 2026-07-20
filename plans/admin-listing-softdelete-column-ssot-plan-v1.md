# admin + listing — Soft-Delete COLUMN SSOT Cleanup (Plan v1)

**Date:** 2026-07-20
**Services:** `tr-crm-core` (admin module) + `tr-content-platform` (listing module)
**Status:** PLAN — awaiting your approval. No code written. No git ops.
**Relation:** follow-up to `softdelete-mixin-methods-relocation-plan-v1.md` (the method plan). This one handles the two **column-level** soft-delete duplications deferred there (§4b). **Independent** of the method plan — the columns already live on `SoftDeleteMixin` today, so neither task needs 0.36.0. Can run before, after, or in parallel.
**Shared-lib impact:** NONE. Both tasks are service-local. No `tr-shared-lib`/`shared-auth-lib` change.

---

## 0. Scope & honesty boundary

This plan removes duplicated soft-delete **columns** (`deleted_at`, `is_active`) — verified DDL-neutral for both. It deliberately does **not**:
- touch auth `is_deleted` or Employee's override (converging those is wrong/breaking — see method plan §4a);
- converge listing's **timestamp/audit** column duplication (a larger, separate effort — see §3 Flag). One concern per plan (KISS).

Both tasks are **zero-DDL** (columns are identical before/after) → **no migration**. Each is gated on an `autogenerate`/`migrate check` producing an EMPTY diff; if any diff appears, STOP and report.

---

## Task A — admin: drop the redundant local `SoftDeleteMixin`

### Evidence (live)
- `tr-crm-core/app/modules/admin/models/base.py:16` — `class BaseModel(Base)` **already declares** `deleted_at` (:40, with `comment=`) and `is_active` (:46, with `comment=`). Every admin model inherits these.
- `tr-crm-core/app/modules/admin/models/mixins.py:49` — a local `class SoftDeleteMixin` re-declares the **same two columns** (same types/defaults/comments).
- `tr-crm-core/app/modules/admin/models/integrations/followup_rule.py:19` — `class FollowUpRule(BaseModel, TenantMixin, AuditMixin, SoftDeleteMixin)` inherits **both** `BaseModel` (which has the columns) **and** the local `SoftDeleteMixin` (which re-declares them). MRO puts `BaseModel` first, so `BaseModel`'s columns win; the mixin's are shadowed/redundant. `TenantMixin`+`AuditMixin` are NOT redundant (admin `BaseModel` lacks `tenant_id`/`created_by`/`updated_by`) — keep them.
- Grep: `FollowUpRule` is the **only** consumer of admin's local `SoftDeleteMixin`. Nothing else imports it.

### Why this, not "adopt tr_shared mixin"
admin is a deliberate full-local-base deviation (own `Base` from `app.core.database`, own mixin set carrying `comment=` on columns, hardcoded index names, no `tenant_id` in base). Swapping admin's columns to tr_shared's mixin would **drop the `comment=` metadata** → a migration, and leave admin 1-of-4-mixins-shared (less consistent). So the correct fix is **internal dedup**, keeping admin local. Do NOT pull tr_shared here.

### Change
1. `followup_rule.py:19` — remove `SoftDeleteMixin` from the base list: `class FollowUpRule(BaseModel, TenantMixin, AuditMixin):`. Columns still come from `BaseModel` (identical).
2. `followup_rule.py:16` — drop `SoftDeleteMixin` from the import (`from app.modules.admin.models.mixins import AuditMixin, TenantMixin`).
3. `mixins.py` — delete the now-dead `class SoftDeleteMixin` (zero remaining refs). Remove any imports it alone used (`Boolean`/`DateTime`/`sqltext`) only if orphaned (TenantMixin/AuditMixin/TimestampMixin in the same file still use them — verify before removing).

### Verify (in `tr-crm-core`)
```bash
cd tr-crm-core
uv run alembic -c app/modules/admin/alembic.ini revision --autogenerate -m _probe  # MUST be empty → delete probe
uv run pytest tests/admin -q          # FollowUpRule CRUD/soft-delete tests green
uv run ruff check app/modules/admin/
grep -rn "SoftDeleteMixin" app/modules/admin --include='*.py' | grep -v alembic   # only… nothing (class gone)
```
- **Gate:** empty autogenerate diff (proves `FollowUpRule`'s table is unchanged — same `deleted_at`/`is_active`), admin tests green, zero `SoftDeleteMixin` refs left in admin.

---

## Task L — listing: extract the 8× duplicated soft-delete column pair

### Evidence (live)
**8 listing models** inline the identical soft-delete pair:
`listing.py:245,255`, `listing_permit.py:86,95`, `listing_portal_publication.py:131,140`, `listing_media.py:92,101`, `listing_status_history.py:76,85`, `listing_pricing.py:135,144`, `listing_portal_field.py:73,82`, `listing_document.py:69,78`.

Every occurrence is byte-identical AND identical to tr_shared's `SoftDeleteMixin`:
```python
deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
is_active: Mapped[bool] = mapped_column(Boolean, server_default=sqltext("true"), nullable=False)
```
- No `index=`/`comment=` on these two columns → **DDL-identical to tr_shared's mixin**.
- listing's `Base = (AsyncAttrs, DeclarativeBase)` (`app/core/database.py:33`) is **2.0-native** → tr_shared's `mapped_column`-based mixin applies cleanly (proven pattern: HR does this on a legacy base already).
- `__table_args__` indexes (e.g. `Index(..., "is_active")`) reference the column **by name** and are unaffected by where the column is declared — they stay in each model. Safe.

### Change — adopt tr_shared `SoftDeleteMixin` (the real cross-service SSOT)
For each of the 8 models:
1. Delete the inline `deleted_at` + `is_active` `mapped_column` lines.
2. Add `SoftDeleteMixin` to the class bases: `class Listing(SoftDeleteMixin, Base):` (mixin first so its columns compose onto `Base`'s metadata = `listing_schema`).
3. Import: `from tr_shared.db import SoftDeleteMixin`.
4. Remove now-orphaned imports per file (`Boolean` / `sqltext` if this pair was their only use — verify per file; many models use `Boolean`/`sqltext` elsewhere).

- **DDL-neutral:** columns are identical; they just come from the mixin now. Verify via autogenerate.
- **Additive bonus:** the 8 models gain `soft_delete()`/`restore()` instance methods (present on the mixin after Plan 1's 0.36.0; harmless before — listing soft-deletes via repository UPDATE today, methods just become available). NOT required for this task.

**Why tr_shared mixin, not a local `ListingSoftDeleteMixin`:** these columns are exactly tr_shared's — a local mixin would reinvent the platform SSOT (the very thing we're fixing). Direct adoption is the permanent fix.

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

**listing also duplicates the timestamp + audit columns inline across the same 8 models** (`created_at`/`updated_at`/`created_by`/`updated_by`), and its timestamp default is `func.current_timestamp()` vs tr_shared's `func.now()`. Converging those:
- would either force a **DDL default migration** (`current_timestamp()` → `now()`), or require a listing-local timestamp mixin that preserves `current_timestamp()` (DDL-neutral but not tr_shared SSOT);
- is a bigger "listing shared base" refactor touching all 8 models + possibly a migration.

That is a **separate plan** (`listing-common-columns-base-ssot`), not bundled here. Flagged so it's tracked, not silently dropped. Recommend deciding it AFTER this soft-delete pass lands cleanly.

Similarly, admin's local `TimestampMixin`/`TenantMixin`/`AuditMixin` (with `comment=`) duplicate tr_shared's — same "full admin base convergence" question, deliberately out of scope (admin's local-base deviation is documented/intentional).

---

## 4. Execution order & independence

- Task A and Task L are **independent** of each other and of the method-relocation plan. Any order.
- Recommended: **Task A first** (tiny, 3 edits, instant verify), then **Task L** (8 models).
- Both are behavior-preserving, zero-DDL. Done-bar per task: empty autogenerate diff · affected tests green · ruff clean · zero leftover dup refs.

**Git:** none by me. You push + relock (though neither task needs a shared-lib relock — both are service-local).

---

## 5. What I need from you

1. **Approve Task A** (admin internal dedup) — low-risk, clear win.
2. **Approve Task L** (listing → tr_shared `SoftDeleteMixin`, soft-delete columns only).
3. **§3 flag** — want a separate plan for listing's timestamp/audit convergence too, or leave listing's non-soft-delete columns as-is for now? (Rec: separate plan later — decide after this lands.)

On approval I execute Task A, verify, then Task L, verify. Report autogenerate diffs at each gate.
