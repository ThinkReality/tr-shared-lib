# Plan — `make_service_include_name` (kill cross-schema autogenerate noise)

**Status:** awaiting approval
**Type:** shared-lib addition + consumer wiring (3 services, 9 env.py)
**Author date:** 2026-07-20

## Problem

Every service's Alembic `env.py` sets `include_schemas=True` (required — services live
in non-default schemas: `admin`, `listing_schema`, `lead`, …). Side effect: on the shared
dev Postgres, autogenerate **reflects every schema in the DB** (hr, finance, lead_mgmt,
dld, realtime, supabase system schemas). `migrate check` then spams:

```
INFO  [alembic.ddl.postgresql] Detected sequence named 'lead_sources_source_id_seq' ... omitting
SAWarning: Did not recognize type 'realtime.user_defined_filter' of column 'filters'
SAWarning: Did not recognize type 'regrole' of column 'claims_role'
```

This is **cosmetic log noise, not a functional error.** `include_object` already scopes
the actual diff to each service's own schema — the diff result is correct. The noise is
just reflection walking foreign schemas.

**Fix:** add Alembic's `include_name` schema hook (official API, confirmed via docs) so
reflection is limited to each service's own schema. Already applied locally to
people-finance (hr + finance env.py) — this plan brings the same fix to the remaining
3 services, done the SSOT way.

## Why shared-lib (not 9 local copies)

5 of the 9 target `env.py` already single-source their scoping via
`make_service_include_object` in `tr_shared.db.migrations.include_object`. The parallel
schema filter belongs in the same place — one definition, not 9 duplicates. This matches
the established pattern (that helper's own docstring exists precisely to kill this class
of per-env.py duplication).

## Scope map (9 env.py across 3 services)

| Service | env.py | SERVICE_SCHEMA | include_object today | allowed schemas for include_name |
|---|---|---|---|---|
| content-platform | modules/cms | `cms` | shared helper | `cms` |
| content-platform | modules/listing | `listing_schema` | shared helper | `listing_schema` |
| crm-core | modules/admin | `admin` | shared helper | `admin` |
| crm-core | modules/task | `tasks` | shared helper | `tasks` |
| crm-core | modules/learning | `lms` | shared helper | `lms` |
| crm-core | modules/activity | `activity` | local | `activity` |
| crm-core | modules/notification | `notification` | local | `notification` |
| crm-core | modules/auth | `auth_schema` | local (special) | `None`, `public`, `auth_schema` |
| lead-management | alembic (root) | `lead` | local | `lead` |

**auth is special** — its `include_object` deliberately manages `auth_schema` **plus** two
`public` resilience tables (`bulkhead_configs`, `circuit_breaker_configs`, see
`app/modules/auth/db/alembic_filters.py::ALLOWED_PUBLIC_TABLES`). Its `include_name` must
therefore allow the default/`public` schema too, or those tables drop out of autogenerate.
This is why the helper takes a **variadic** allow-list, not a single schema.

## Part A — shared-lib change (tr-shared-lib) — YOU push + relock

### A1. Add helper to `src/tr_shared/db/migrations/include_object.py`

Append (mirrors `make_service_include_object` in the same file):

```python
IncludeName = Callable[[str | None, str, dict[str, str]], bool]


def make_service_include_name(*allowed_schemas: str | None) -> "IncludeName":
    """Return an ``include_name`` callable for Alembic's ``context.configure``.

    Restricts which *schemas* autogenerate reflects. With ``include_schemas=True``
    Alembic reflects every schema in the database; on a shared dev Postgres that
    means foreign services' schemas pollute the log with sequence/type warnings.
    Limiting reflection to the service's own schema(s) keeps ``check``/autogenerate
    scoped and quiet.

    ``include_object`` still filters the actual diff; this only bounds reflection.

    Args:
        *allowed_schemas: Schema names to reflect. Pass ``None`` to allow the
            default (``public``) schema — needed by services (e.g. auth) that
            manage a few tables outside their own named schema.

    Usage in env.py::

        include_name = make_service_include_name("admin")
        context.configure(..., include_schemas=True, include_name=include_name)
    """
    allowed: frozenset[str | None] = frozenset(allowed_schemas)

    def include_name(
        name: str | None,
        type_: str,
        parent_names: dict[str, str],  # noqa: ARG001 — part of Alembic API
    ) -> bool:
        if type_ == "schema":
            return name in allowed
        return True

    return include_name
```

> Note: `public` in Alembic reflection surfaces as the default schema → `name is None`.
> For auth pass **both** `None` and `"public"` so it's robust whichever way the
> installed Alembic version reports the default schema.

### A2. Export in `src/tr_shared/db/migrations/__init__.py`

- Add `make_service_include_name` to the import from `.include_object`.
- Add `"make_service_include_name"` to `__all__`.
- Add a bullet to the module docstring.

### A3. Tests — `tests/unit/db/migrations/test_include_object.py` (or new `test_include_name.py`)

- `make_service_include_name("admin")` → `include_name("admin","schema",{})` True;
  `include_name("hr","schema",{})` False; `include_name(None,"schema",{})` False.
- Variadic: `make_service_include_name(None, "public", "auth_schema")` →
  True for `None`, `"public"`, `"auth_schema"`; False for `"hr"`.
- Non-schema type passthrough: `include_name("anything","table",{})` True.

### A4. Version bump `pyproject.toml`

`0.36.0` → `0.37.0` (additive, backward-compatible).

### A5. Your steps

1. Review this plan.
2. I write A1–A4 in tr-shared-lib (no push).
3. **You** push tr-shared-lib + relock the 3 consumers:
   `tr-content-platform`, `tr-crm-core`, `tr-lead-management`
   (each: `uv lock --upgrade-package tr-shared-lib && uv sync --frozen`).
4. Tell me — then I do Part B.

## Part B — consumer wiring (9 env.py) — after relock

Each file: import the helper, build `include_name`, pass it to **both** `context.configure`
calls (offline + online). No other lines change.

**5 shared-helper users** (cms, listing, admin, task, learning) — add to the existing
`from tr_shared.db.migrations import (...)` block:

```python
include_name = make_service_include_name(SERVICE_SCHEMA)
# both configure() calls: add  include_name=include_name,
```

**activity, notification, lead** (local include_object) — add the import + one line:

```python
from tr_shared.db.migrations import make_service_include_name
include_name = make_service_include_name(SERVICE_SCHEMA)
# both configure() calls: add  include_name=include_name,
```

**auth** (special) —

```python
from tr_shared.db.migrations import make_service_include_name
include_name = make_service_include_name(None, "public", "auth_schema")
# both configure() calls: add  include_name=include_name,
```

## Part C — verification (per service)

For each service, against its test DB (with a foreign schema injected to prove the point):

```bash
cd <service>
make test-db-up                     # or docker compose -f docker-compose.test.yml up + migrate upgrade head
docker exec <pg> psql -U .. -d .. -c "CREATE SCHEMA foreign_svc; CREATE TABLE foreign_svc.x (id serial primary key);"
uv run migrate check                # crm-core/content: multi-tree runner; lead: alembic check
#   expect: NO foreign-schema INFO/SAWarning lines; each tree "No new upgrade operations detected"
make test-db-down
```

Plus `ruff check` clean on every edited env.py.

## Done bar

- tr-shared-lib: helper added, exported, unit-tested, version 0.37.0, ruff clean. (YOU push+relock.)
- 9 env.py wired, ruff clean.
- `migrate check` on each service: zero foreign-schema noise, diffs still correct.
- auth still reflects its 2 public resilience tables (regression check: auth `check` clean).

## Out of scope

- people-finance (already fixed locally this session — could later migrate to the shared
  helper for full fleet SSOT, but not required; its env.py uses fully local functions).
- Any change to `include_object` behavior or actual migration content.
