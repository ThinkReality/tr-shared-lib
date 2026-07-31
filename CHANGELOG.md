# Changelog

All notable changes to tr-shared-lib will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.52.0] - 2026-07-31

### Fixed
- `tr_shared.testing.lanes.run_needs_infrastructure` no longer consults `markexpr`
  before the paths. `pytest tests/unit/ -m integration` used to short-circuit to
  `True` and provision a Postgres + Redis pair for a run that can select nothing:
  the lane marker is *derived from the path*
  (`plugin.pytest_collection_modifyitems`), so no test under a unit path ever
  carries the integration marker.

### Changed
- Adopted ruff as the lint + format gate (config, dev dependency, CI job,
  pre-commit hooks) and applied `ruff check --fix` + `ruff format` across the
  tree. `.git-blame-ignore-revs` records the reformat commit so `git blame` skips
  it. No behavioural change — style only, but it is why this release touches 148
  files.
- Rewrote 9 tests left behind by earlier source rewrites (`#7`). They asserted
  against signatures that no longer existed and had been passing vacuously.

### Why
The lane bug cost this library's own unit lane roughly 90 seconds per run, and
failed outright whenever the Docker daemon was busy — the shape every service in
the fleet then inherits. It is the third instance of one root cause: the lane is
decided from `argv` *before* anything is collected, so every wrong answer is a
guess made too early. Paths now outrank the marker expression.

`markexpr` stays in the signature deliberately. The plugin passes it, and keeping
it makes the regression explicit in the tests rather than something a future
refactor can quietly reintroduce.

### Migration
None. A bare `pytest -m integration` still provisions — not because of the marker,
but because it names no paths, which is unchanged behaviour. Services get this on
their next pin bump; no code change is required of them.

## [0.51.0] - 2026-07-31

### Added
- `HttpHeader.ORIGINAL_IP` (`X-Original-IP`) — the originating client's IP as
  observed by the gateway at the socket. The gateway strips any inbound copy
  before re-deriving it, so downstream reads a gateway-asserted value rather than
  a caller-supplied one.

### Removed
- **Breaking:** `register_integration_cache_handlers` is no longer exported from
  `tr_shared.integrations`, and the event-driven cache-invalidation path it wired
  up is gone. `IntegrationConfigClient` now caches behind a plain TTL.

### Why
`ORIGINAL_IP` is deliberately **not** a `shared_auth_lib.SignedHeader` member.
Adding one there changes the canonical string of every signed request, which forces
a lockstep redeploy of the entire fleet — a gateway on one version and a service on
another produce different signatures and every route 403s. Because it is unsigned,
downstream must use it only for bucketing (rate limits), never for authorization.

The invalidation handlers were removed rather than fixed because the event path
duplicated what the TTL already guarantees, and a second invalidation mechanism is
a second thing that can silently stop working.

### Migration
No consumer in the fleet imported `register_integration_cache_handlers` — verified
across all eight services and shared-auth-lib before this entry was written — so
the removal is a no-op in practice. Anything outside the fleet that did import it
should delete the call: the TTL cache needs no registration.

## [0.50.0] - 2026-07-30

### Changed
- `tr_shared.contracts.s2s.wam_leads.BASE_PATH` moved from `/api/v1/leads` to
  `/api/v1/internal/leads`.

### Added
- A worked "adding a provider" guide on `monitoring.factory`, documenting the five
  steps and the two things they hide: a provider needing its own configuration
  still requires new kwargs on both `create_*_provider` and `setup_monitoring`, and
  the `provider` arguments are typed `str` rather than the enums, so a typo raises
  from the factory's terminal `ValueError` instead of failing at the call site.

### Why
The `/internal` prefix is load-bearing, not cosmetic. tr-whatsApp-marketing-agent
mounts `GatewayHMACMiddleware` app-wide, which 403s any unsigned request outside its
skip list, and `/api/v1/internal/` is that skip list's only business-route entry.
The contract has to name the path the provider actually serves, or tr-lead-management's
`WAMClient` signs nothing and gets a 403 that looks like an auth bug.

### Migration
Consumers reading `BASE_PATH` from the contract need no change — that is the point
of the contract. Anything that hardcoded `/api/v1/leads` for WAM must be repointed.

## [0.49.3] - 2026-07-30

### Added
- `tr_shared.testing.guards.assert_environment_vocabulary` (G13) — fails a
  service whose shell scripts compare `$ENVIRONMENT` against anything outside
  the canonical four (`development`, `test`, `staging`, `production`).
- `tr_shared.testing.guards.iter_shell_files`, plus an `iterator=` parameter on
  `find_violations`, so a guard can walk `.sh` files through the same
  `Exemption`/staleness machinery the Python guards already use.

### Fixed
- `TEST_DATABASE_URL` (the documented no-Docker escape hatch) never ran the
  service's `migrate_command`. The branch returned before `provision()`, so the
  database stayed empty and the run failed with `relation "..." does not exist`.
- The same branch pointed cache, Celery broker and Celery result backend at a
  single `TEST_REDIS_URL`, collapsing the three-index isolation the container
  path deliberately provides.

### Why
The environment-vocabulary guard this replaces lived in one service and matched
`ENVIRONMENT==`/`!=` adjacently. Shell writes `[ "$ENVIRONMENT" = "dev" ]` — a
quote and a space intervene — so it scored **zero hits on four scripts holding
five real violations**. It also enumerated the wrong spellings (`dev|local|prod
|stage`) rather than the right ones, so `qa`, `uat` and `Production` passed. G13
inverts that: anything not in the canonical set is a violation.

The override branch is what crm-core's CI takes. It stayed red for five
consecutive runs while its workflow comment claimed schema construction was
handled elsewhere — the branch reported success by returning early, which is the
worst failure shape available. `run_migrations()` and `redis_triple()` are now
extracted and shared with `provision()`, because two copies of "how this service
migrates" is what let the two paths drift apart in the first place.

### Migration
G13 is opt-in — call `assert_environment_vocabulary(service_root)` from a
service's guard test. Two services currently fail it (`tr-crm-core`,
`tr-people-finance`); adopt after fixing their scripts, not before.

Services already setting `TEST_DATABASE_URL` will now have migrations run
against that database on every session. This is the intended behavior change:
Alembic `upgrade head` is idempotent, so an already-migrated database is a
no-op.

## [0.49.2] - 2026-07-30

### Fixed
- `tr_shared.events.EventConsumer._process_message` now routes events with no
  registered handler to the dead-letter queue (when one is configured),
  instead of silently ACKing and discarding them with only a WARNING log.

### Why
Every consumer group on the shared `tr_event_bus` stream receives every event
type published by every module — a consumer registering a handler for one
event type still receives all the others. Discarding unknowns with no DLQ
trail meant a real production bug (missing handler registration, wrong event
type name, etc.) was invisible — the event was just gone. The malformed-
message and retries-exhausted paths already route to DLQ; the no-handler path
was the one gap. `tr-crm-core`'s notification module had already independently
patched around this exact gap with a `NotificationEventConsumer` subclass
override — this fix makes that override redundant (see `tr-crm-core`'s
`2026-07-30-event-consumer-dlq-routing.md` plan for its removal).

### Migration
None — drop-in fix, no signature change. Bump the pin and redeploy. Consumers
that previously relied on unknown events vanishing silently will now see them
in `{stream_name}_dead_letter` — this is the intended behavior change.

## [0.48.1] - 2026-07-29

### Fixed
- `tr_shared.events.create_outbox_drainer_task` now runs its drain task via
  `run_async_in_celery` instead of a raw `asyncio.run()` per tick.

### Why
`asyncio.run()` opens and closes a fresh event loop on every tick. Services
that also adopted `run_async_in_celery` (one persistent loop per worker
process) for their other Celery tasks got `RuntimeError: ... attached to a
different loop` on the outbox-drainer task specifically, because the two
loop-management strategies fought over the same async DB engine/redis
connections inside the same forked worker process.

### Migration
None — drop-in fix, no signature change. Bump the pin and redeploy.

## [0.48.0] - 2026-07-29

### Changed (BREAKING)
- `BaseServiceSettings.ENVIRONMENT` is now typed `Environment`, not `str`.
  Non-canonical values (`dev`, `local`, `prod`, `stage`, `Production`) raise at
  startup instead of being silently accepted.

### Why
`ENVIRONMENT=prod` previously booted a service with every production guard
skipped — empty `DATABASE_URL`, wildcard CORS, blank `SERVICE_TOKEN` and
localhost Redis all accepted, because the validator matched the exact string
`"production"`.

### Migration
Set `ENVIRONMENT` to one of `development`, `test`, `staging`, `production`.
Replace any local dev-environment set with `settings.is_local`.

## [0.47.0] - 2026-07-28

### Added
- `tr_shared.testing.transaction_guard` — G6d: catches `.delay()`/`.apply_async()`
  dispatched while the caller's tracked SQLAlchemy session still has an open,
  uncommitted transaction, under Celery eager mode. `install_transaction_guard(app)`
  connects to `task_prerun` (the signal Celery's tracer fires for both eager and
  real execution — `before_task_publish` does NOT fire in eager mode, since
  `apply_async()` short-circuits straight to `apply()`); `track_session(session)`
  opts a session in around the dispatch to check.
- `tr_shared.testing.stubs` — shared test fakes for the two third-party
  integrations with real cross-service duplication (PropertyFinder, Bayut — each
  independently hand-mocked in crm-core, content-platform, and lead-management
  today, with three different mocking mechanics). `MockTransportBuilder`
  (`stubs/http_stub.py`) drives the real `httpx.AsyncClient`/`Client` via
  `httpx.MockTransport`, not patched internals. `PropertyFinderStub`/`BayutStub`
  wrap it with the endpoints the fleet's clients call, plus
  `sign_propertyfinder_webhook`/`sign_bayut_webhook`, which sign fake webhook
  payloads with the same production verifiers (`tr_shared.webhooks.providers.*`)
  real deliveries are checked against.

### Notes
- Supabase, Gemini, HikCentral, and SuprSend were investigated for the same
  treatment and explicitly NOT built: each is either single-service or has no
  existing stub at all — no real duplication to remove, so a shared fake would be
  a speculative abstraction with nothing to deduplicate.

## [0.45.0] - 2026-07-28

### Added
- `tr_shared.testing` — reusable structural guards for service test suites.
  `tenant_header_guard` exposes an AST scanner (`find_raw_tenant_header_readers`,
  `scan_source_for_raw_tenant_header_reads`) plus assertion helpers
  (`assert_no_undocumented_raw_tenant_header_reads`, `assert_no_stale_exemptions`,
  `assert_exemptions_are_machine_verified`) and an `Exemption` dataclass.

### Notes
- The invariant guarded is fleet-wide — the raw `X-Tenant-ID` header is identity
  CONTEXT, never an authorization input — but the code that can break it lives in
  eight repositories. A private per-service copy guarded one eighth of the risk:
  running the shared version across the fleet immediately surfaced an unguarded
  reader in tr-api-gateway and one in tr-lead-management.
- An `Exemption` must carry a machine-checkable claim (`requires_symbols`, or
  `must_be_inert`), not prose alone. A prose reason stays true-looking long after
  the gate it describes is deleted.
- The matcher handles the forms real code uses, not just literals: normalised keys
  (`HttpHeader.TENANT_ID.value.lower()`), a headers mapping arriving as a function
  parameter, `dict(request.headers)` wrappers, module-level key constants,
  subscript access, `Header(alias=...)` params, and sources carrying a UTF-8 BOM.
  Outbound client headers are deliberately not flagged.
- Additive only. No existing module changed; nothing to migrate.

## [0.44.0] - 2026-07-27

### Added
- `tr_shared.contracts.Environment` — the canonical deployment-environment
  vocabulary (`development`, `test`, `staging`, `production`) with an `is_local`
  property. Single source of truth for every service and library.
- `BaseServiceSettings.is_production`, `.is_development`, `.is_local`.

### Changed
- `BaseServiceSettings.validate_production_config` now branches on
  `self.is_production` instead of comparing `ENVIRONMENT` to a string literal.

### Notes
- Additive and non-breaking. `ENVIRONMENT` is still typed `str`; the strict
  retype ships in 0.45.0 once every deployed value is canonical.

## [0.43.0] - 2026-07-27

### Changed
- `db.BaseRepository` now raises `ValueError` when `tenant_id` is `None` on
  `get_by_id`, `get_all`, `find_by_field`, `find_by_field_in`, `get_paginated`,
  `count` and `soft_delete`. Previously such a call rendered
  `tenant_id IS NULL` against a NOT NULL column — failing closed, but silently,
  so a caller that lost its tenant saw an empty result set instead of an error.
  Matches the existing guard on `create()`.

## [0.40.1] - 2026-07-24

### Added
- `tr_shared.logging.safe_log_context`, `sanitize_traceback`, `sanitize_for_logging`,
  `sanitize_context` — promoted from tr-crm-core's notification module. The shared
  structlog processor (`_mask_sensitive_fields`) only redacts by key name, missing
  raw exception text and `exc_info=True` tracebacks (SQL bound parameters, device
  tokens, emails). `safe_log_context(error)` sanitizes both `str(error)` and the
  formatted traceback for use in `extra={**ctx, **safe_log_context(e)}` logging
  calls, available to every service now instead of just tr-crm-core.

## [0.40.0] - 2026-07-24

### Added
- `contracts.s2s.listing_internal.PortalSyncStatus` — SSOT for
  `listing_schema.listing_portal_publications.portal_sync_status`
  (`pending`/`syncing`/`synced`/`error`/`disabled`/`action_required`), the
  CHECK-constrained vocabulary owned by tr-content-platform. tr-crm-core
  previously declared its own disagreeing copy (`RecentSyncStatus` =
  `success`/`failed`/`pending`), which made `status_filter=success|failed`
  match zero rows and made every sync-activity description fall through to the
  `"Sync pending"` fallback. Both become structurally impossible once both
  sides import this.
- `contracts.s2s.listing_internal.recent_sync_activity()` path builder plus
  `PortalSyncActivityRow` / `PortalSyncActivityPage` response models — the S2S
  contract that replaces tr-crm-core's cross-schema raw SQL read of
  `public.listing_portal_publications`.
- `contracts.s2s.listing_internal.PORTAL_PUBLICATIONS_BASE_PATH` — second
  resource prefix under the same provider root.
- CI now runs `tests/contracts` (it previously ran only the event-bus suites, so
  no S2S contract test was gated).
- `contracts.s2s.listing_internal.PortalSyncActivityQuery` — the query vocabulary
  for that endpoint (`portal_name`, `sync_status`, `limit`, `hours_back`) with
  `extra="forbid"`, so a drifted parameter name is a 422 rather than an HTTP 200
  with the filter silently ignored. This is also what lets tr-crm-core delete
  `RecentSyncStatus` outright — it otherwise survives solely to validate
  `status_filter`.

### Removed
- `contracts.s2s.listing_internal.BASE_PATH` removed and replaced by
  `INTERNAL_ROOT` + `LISTINGS_BASE_PATH` + `PORTAL_PUBLICATIONS_BASE_PATH`. A
  bare `BASE_PATH` became ambiguous once the module carried two resources. No
  caller imported the old name (verified across tr-crm-core,
  tr-content-platform, tr-lead-management); every emitted path is
  byte-identical, pinned by `test_existing_listing_paths_unchanged_after_prefix_split`.

## [0.33.0] - 2026-07-15

### Added
- **PEP 561: `py.typed` marker.** `tr_shared` now ships as a typed package, so
  downstream services' type checkers see its real annotations instead of treating
  every symbol as `Any`. Notably `BaseRepository.db_session` is now seen as
  `AsyncSession`, so `.execute(...).scalar_one_or_none()` etc. carry real types.

### Changed
- `db.base` mixins (`TimestampMixin`, `TenantMixin`, `AuditMixin`,
  `SoftDeleteMixin`) and `BaseModel.id` converted from bare `Column` to
  SQLAlchemy 2.0 `Mapped[...]` / `mapped_column(...)`. Type-only, runtime
  byte-identical — every model inheriting `BaseModel` now has correctly typed
  `id`/`tenant_id`/`created_at`/`updated_at`/`created_by`/`updated_by`/
  `deleted_at`/`is_active` for consumers' type checkers.

### Fixed
- `__version__` realigned to `[project].version` (had drifted to 0.32.1).

## [0.32.2] - 2026-07-15

### Changed
- `events.payloads.admin.AdminLeadScoringDeletedV1.deleted_count`: tightened from
  `int | str` to `int`. The `"all"` string sentinel on delete-all is gone — the
  emitter (tr-crm-core lead-scoring) now reports the real deactivated row count as
  an int. No consumer read the string form.

## [0.32.1] - 2026-07-02

### Fixed
- `middleware.register_exception_handlers`: `validation_exception_handler` now
  wraps `exc.errors()` in `fastapi.encoders.jsonable_encoder`. A Pydantic v2
  `field_validator` that raises `ValueError` leaves a live `ValueError` object in
  `ctx.error`, which is not JSON-serializable — the raw `exc.errors()` crashed
  `JSONResponse` serialization, so `GlobalErrorHandlerMiddleware` turned it into a
  **500 instead of the intended 422**. Any downstream service with a raising
  field-validator was affected (e.g. tr-whatsApp-marketing-agent phone validation).

## [0.25.0] - 2026-06-13

### Added
- `tr_shared.db.run_async_migrations(url, do_run_migrations, *, connect_args=None)`
  — canonical async-engine runner for Alembic `env.py` online mode. Builds a
  NullPool asyncpg engine in Supavisor session mode (6543→5432) and drives
  `do_run_migrations` via `connection.run_sync`. Consolidates the
  `create_async_engine` + `run_sync` boilerplate each async-migration service
  hand-rolled. Part of standardising the platform on a single asyncpg driver
  for both runtime and migrations (no psycopg2/psycopg3).

### Deprecated
- `to_sync_url` / `to_migration_url` — they force the sync psycopg2 driver.
  Migrated services should use `run_async_migrations` + `to_session_mode_url`.
  Retained for services not yet converted.

## [0.24.0] - 2026-06-13

### Changed
- `CMSBlogEventV1.blog_slug` is now optional — blog lifecycle events (notably the
  bulk-operations path) don't all carry a slug, so requiring it was wrong. Page
  events still require `page_slug` (always present).

## [0.23.0] - 2026-06-13

### Changed
- `CMSPageEventV1` and `CMSBlogEventV1` gained required `entity_type` + `entity_id`
  fields — they are carried on the wire (the CMS publish task injects them) and
  read by the notification/activity consumers for entity linking. Brings the CMS
  payloads in line with the hr/finance/listing-audit/lead models. (Enables the
  content-platform CMS typed-payload adoption, W1-C2.)

## [0.22.0] - 2026-06-13

### Changed (BREAKING)
- `EventProducer.__init__` now **requires** `source_service` (keyword-only) and
  validates it against the `Feature` spine at construction. The old
  `source_service="unknown"` default is gone — a deployable name or any
  non-Feature value raises `ValueError`. This closes the permanence hole where
  the public constructor bypassed `make_event_producer`'s Feature guard. Bare
  `EventProducer()` now raises `TypeError`. All in-tree service emitters already
  pass valid Feature values; one WAM site constructing a bare producer must be
  fixed on adoption.

### Added
- Typed payload modules completing the P1-8 set:
  - `payloads/cms.py` — `CMSPageEventV1` (+ Updated/Published/ReviewRequested/
    Approved/Rejected subclasses), `CMSBlogEventV1` (+ Updated), and
    `CMSLandingPagePublishedV1` with nested `CMSLandingPageContextV1` /
    `CMSLandingPageMediaV1`. Canonical redesign: fixed `actor_id`/`recipient_id`
    replace the legacy dynamic `{action}_by` keys.
  - `payloads/lead.py` — `LeadCreatedV1` (unified superset of the two emit
    shapes), `LeadAssignedV1`, `LeadStatusChangedV1`, `LeadQualifiedV1`,
    `LeadFollowupDueV1`. PII fields carry hashed values only.
  - `payloads/wam.py` — `WAMLeadQualifiedV1` (+ nested `WAMQualificationResultV1`),
    `user_number` digits-only validator.
  - `payloads/listing.py` — `ListingAuditEventV1` (single model for the 13
    audit-path listing.* events; drops the redundant `event_type`-in-data key,
    retains `entity_type`).
  - `payloads/finance.py` — `FinanceInvoiceEventV1`,
    `FinanceCardTransactionImportedV1`, `FinanceCardTransactionMatchedV1`.
    (`finance.commission.paid` has no emitter and is intentionally unmodelled.)
  - `payloads/hr.py` — `HRApplicationSubmittedV1`, `HRApplicationStageChangedV1`
    (the latter reused for hired/rejected).

### Fixed
- `pyproject.toml` version synced to `__version__` (was 0.19.0 vs 0.21.0). A new
  parity test asserts the two never drift again.

## [0.21.0] - 2026-06-12

### Added
- `FinanceEvents.EXPENSE_APPROVAL_REMINDER` (`finance.expense.approval_reminder`) —
  emitted by people-finance's approval-reminder task (P5 C2 adoption).
- `EntityType.FINANCE_EXPENSE` (`finance.expense`) — for people-finance's approval
  entity-type adoption (P5 D1; replaces the local `ApprovalEntityType.EXPENSE`).

## [0.20.0] - 2026-06-12

### Added
- `tr_shared.events.payloads.listing`: typed payloads for the PropertyFinder-keyed
  listing lifecycle events (single-shape, domain-path only) — `ListingPfEventV1`
  (base), `ListingSaleV1` (sold/rented), `ListingExpiredV1`, `ListingRepublishedV1`,
  `ListingDeletedV1`. Consumed by tr-content-platform listing adoption (P4 C2 clean
  subset). The dual-shape status-change events + cms dynamic-key events are NOT
  modelled yet (need emitter canonicalisation).

## [0.19.0] - 2026-06-10

### Added
- `tr_shared.events.payloads`: typed `{Feature}{Event}V1` models for every event
  crm-core produces — `activity` (comment added/edited/deleted, log_created),
  `admin` (lead_source/assignment_rule/lead_scoring/nurture_campaign/module +
  `IntegrationPlatformEventV1` moved here from crm-core, now str ids),
  `notification` (sent, lead_reassign/overdue_requested), `auth`
  (admin.user.created/updated, admin.role.assigned), `lms` (quiz
  generated/assigned/expired). All `EventPayload` (`extra="forbid"`), fields
  field-exact to today's emitted dicts. Publish-side of D-PAYLOAD (P3-S2-4).

### Changed
- `IntegrationPlatformEventV1`: `platform_id`/`tenant_id` `UUID`→`str` and base
  `BaseModel`→`EventPayload` (callers stringify ids at emit; wire bytes unchanged).

## [0.18.0] - 2026-06-10

### Added
- `FinanceEvents`: 11 expense/invoice/card_transaction members (`EXPENSE_CREATED`,
  `EXPENSE_SUBMITTED`, `EXPENSE_APPROVED`, `EXPENSE_REJECTED`, `EXPENSE_PAID`,
  `EXPENSE_REIMBURSED`, `INVOICE_CREATED`, `INVOICE_SENT`, `INVOICE_PAYMENT_RECORDED`,
  `CARD_TRANSACTION_IMPORTED`, `CARD_TRANSACTION_MATCHED`).
- `DealEvents.AMOUNT_CHANGED`; `HREvents.OFFER_SENT` / `OFFER_ACCEPTED`.
- Completes the registries the notification + activity-logger consumers match on
  (P3-S2-3) — closes the last bare-string consume gaps in crm-core.

## [0.17.0] - 2026-06-10

### Added
- `NotificationEvents.SENT = "notification.sent"` — registry member for the
  notification-emitted `notification.sent` event (closes the last bare-string gap
  blocking crm-core's event-registry adoption, P3-S2).

## [0.16.0] - 2026-06-08

### Added
- `tr_shared.events.payloads`: strict `EventPayload` base (`extra="forbid"`) and
  the `task` feature's typed payload models (pilot).
- `tr_shared.events.helpers`: `publish_event` (one standard typed publish path),
  `parse_payload` (one standard typed consume path), and `make_event_producer`
  (constructs a producer whose `source` is a `Feature` — invariant guard).

Additive. Other features' payloads are added with each service's adoption.

## [0.15.0] - 2026-06-08

### Added
- `tr_shared.contracts` package: `Feature` taxonomy spine (17), `EntityType`
  flat StrEnum with `.feature()`, `Priority`/`Channel` enums, and a structured
  `GLOSSARY` with a drift-guard test.
- Event registries: `TaskEvents`, `NotificationEvents`, `WAMEvents`.
- `CMSEvents`: page-review events (`PAGE_UNPUBLISHED`, `PAGE_REVIEW_REQUESTED`,
  `PAGE_APPROVED`, `PAGE_REJECTED`).

Purely additive — no existing symbols changed. Service adoption + data
migrations land in later phases.

## [0.12.0] - 2026-04-21

### Added — Phase 0 foundations for tr-be-admin-panel PR #87 permanent fixes

#### `tr_shared.db.migrations` (NEW sub-package)
- `concurrent_index_context(op)` — context manager wrapping Alembic's `autocommit_block()` for safe `CREATE INDEX CONCURRENTLY` on populated tables.
- `add_check_constraint_deferred(op, *, table, schema, constraint_name, predicate)` — adds CHECK via `NOT VALID` + `VALIDATE CONSTRAINT` pattern.
- `add_fk_deferred(op, ...)` — same deferred pattern for FKs; **refuses cross-schema references** with `CrossSchemaFKError` per TR service-isolation rules.
- `dedup_with_table_lock(op, *, table, schema, partition_by, order_by, ...)` — LOCK TABLE SHARE ROW EXCLUSIVE + CTE dedup. Prevents concurrent-write race windows during migration dedup.
- `bootstrap_schema_and_version_table(connection, *, schema, version_table)` — one-shot `CREATE SCHEMA` + optional version-table relocation from legacy schema. Replaces fragile double-commit patterns in service `env.py` files.
- `make_service_include_object(target_schema, target_metadata)` — Alembic `include_object` filter covering tables, indexes, constraints, FKs, sequences. Previous per-service implementations only filtered tables.
- `UNDELIVERED_EVENTS_COLUMNS` SQL constant for per-service outbox table migrations.

#### `tr_shared.exceptions`
- `BaseAPIException` contract freeze: any subclass skipping `super().__init__(...)` now raises `TypeError` at construction time instead of producing a broken response at render time. Enforced via `__init_subclass__` wrapper.
- Module-level `__all__` frozen.

#### `tr_shared.integrations`
- `GEMINI_PLATFORM_NAME = "Google Gemini AI"` — canonical string.
- `KNOWN_PLATFORM_NAMES` extended with `GEMINI_PLATFORM_NAME` — admin-panel CHECK constraint generated from this frozenset prevents drift.
- `PUBLIC_CONFIG_KEYS` — **allowlist** of non-sensitive platform config keys. Replaces blocklist-based secret redaction across services.
- `sanitize_public_config(config)` — helper that drops any key not on the allowlist.

#### `tr_shared.events`
- `DurableEventPublisher` — transactional-outbox publisher. Writes to `{schema}.undelivered_events` via caller's `AsyncSession`, joining caller's transaction. Raises `RuntimeError` when called outside a transaction.
- `drain_outbox(session_factory, producer, schema, ...)` — drainer that publishes pending rows to Redis Stream, applies `RetryPolicy` with exponential backoff, dead-letters after `max_retries`, fires `on_dead_letter` callback. Events are never silently lost.
- `create_outbox_drainer_task(celery_app, ...)` — Celery task factory pairing with `drain_outbox`.
- `DEFAULT_DRAINER_INTERVAL_SECONDS = 30` — recommended beat interval; services override per their own load profile.

#### `tr_shared.http`
- `InternalServiceClient` — typed wrapper around `ServiceHTTPClient` for `/api/v1/internal/*` consumers. Parses `SuccessResponse` envelope, injects `X-Tenant-ID` header, translates HTTP status + error body into `tr_shared.exceptions.*` (400→`ValidationError`, 401→`AuthenticationError`, 403→`AuthorizationError`, 404→`NotFoundError`, 409→`ConflictError`, 429→`RateLimitError`, 5xx/timeout→`ServiceUnavailableError`/`ServiceTimeoutError`).

### Notes
- No breaking changes to existing exports. New `BaseAPIException` subclass contract is stricter but all in-library subclasses already comply; external subclasses should be audited before upgrading.
- `EventProducer` (at-most-once) is **not** deprecated; `DurableEventPublisher` is the new path for reliable delivery.
- Sibling service `alembic/env.py` files should migrate to `bootstrap_schema_and_version_table` + `make_service_include_object` in Phase 3 of the parent plan.

## [0.6.0] - 2026-03-01

### Added
- Monitoring module: `setup_monitoring()` single-call setup for Prometheus + Loki + Tempo
- MetricsMiddleware for automatic HTTP request metrics (counters, histograms, active requests)
- PersistenceMiddleware (Layer 2) for Redis-buffered request logging to central DB
- Provider abstraction: MonitoringProviderFactory with Prometheus, Loki, OTLP, and Noop adapters
- LokiHandler for structured log shipping to Grafana Loki
- Distributed tracing setup via OpenTelemetry OTLP/gRPC exporter
- Prometheus endpoint: standalone HTTP server or FastAPI route strategies
- Rate limiter module: sliding window and fixed window algorithms
- RateLimitMiddleware and `rate_limit()` FastAPI dependency
- MemoryFallback for rate limiting when Redis is unavailable
- Events module: EventProducer and EventConsumer via Redis Streams
- EventEnvelope canonical format, dead-letter queue, retry policies
- InMemoryIdempotencyChecker for deduplication

## [0.5.0]

### Added
- Cache module: CacheService with provider-agnostic JSON serialization
- CacheProviderFactory with Standard Redis and Upstash adapters
- CacheInterface abstract base and CacheResult (hit/miss/error distinction)
- HTTP module: ServiceHTTPClient with exponential backoff retry
- CircuitBreaker state machine (CLOSED -> OPEN -> HALF_OPEN)
- Celery module: `create_celery_app()` factory with pre-configured defaults

## [0.4.0]

### Added
- Database module: BaseModel with TimestampMixin, TenantMixin, AuditMixin, SoftDeleteMixin
- BaseRepository with mandatory tenant_id scoping on all queries
- Async engine and session factories (PgBouncer-safe NullPool)
- Middleware module: CorrelationIDMiddleware, GlobalErrorHandlerMiddleware, LoggingMiddleware
- Config module: BaseServiceSettings base class for all services
- Logging module: `configure_logging()` with JSON output (production) and text (development)
- Redis module: async client singleton with connection pooling
