# Changelog

All notable changes to tr-shared-lib will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.67.0] - 2026-08-21

### Changed
- **BREAKING — an unhandled event type is now acked, not dead-lettered.** One stream
  feeds every consumer group, so most events are not a given group's. Dead-lettering
  them filled the capped DLQ and pushed out real failures: on staging, 4,000 of the
  4,000 newest entries were "No handler registered" and none was a real failure. The
  DLQ still takes malformed payloads, handler exceptions and exhausted retries.

### Removed
- **BREAKING — `EventConsumer.register_ignored()`.** It made each consumer list the
  events it did *not* handle, which no one can keep correct. Now that unhandled types
  are acked by default it does nothing, so it is deleted rather than kept as a no-op.
  Drop the call; no replacement.

## [0.66.3] - 2026-08-17

### Fixed
- **`exc_info=True` was silently dropped in JSON/production logs** —
  `configure_logging`'s `ProcessorFormatter` was built with the legacy
  singular `processor=renderer` kwarg, which only runs the renderer itself
  and never a traceback processor. Every `logger.error(..., exc_info=True)`
  fleet-wide rendered as the literal `{"exc_info": true, ...}` in JSON output
  instead of a real traceback — production debugging had to reconstruct root
  causes from message context alone. Confirmed dev/text output
  (`ConsoleRenderer`) was unaffected; this was a JSON-path-only defect.
  Fixed by switching to the current `processors=[...]` list API:
  `remove_processors_meta` (strips internal `_record`/`_from_structlog` keys)
  → `format_exc_info` (JSON path only — renders a plain-text `exception`
  field; `dict_tracebacks` was considered and rejected, it leaks frame
  locals by default) → the renderer.

### v0.66.2 is a dead tag — do not pin to it
`v0.66.2` exists on this repo and will never be deleted (tags are frozen, see
root `CLAUDE.md`'s Upgrading Shared Libs section), but it points at `0c3f7da`
— the same commit `v0.66.1` points at. It was cut against a feature branch's
tip (`fix/hikcentral-attendance-probe-time-format`, not yet merged to `main`)
before the exc_info fix above had even been committed, so it contains
**neither** the fix nor anything past `v0.66.1`. Same failure shape as
`v0.65.0` below: discovered before any consumer relocked against it. Use
`v0.66.3` or later.

## [0.66.1] - 2026-08-17

### Fixed
- **`hikcentral_probe_attendance` sent `beginTime`/`endTime` as epoch-millisecond
  integers** — the live device rejects this with `"Incorrect request parameter.
  [beginTime parameter error]"`, misclassified as `HIKCENTRAL_LICENSE_001`
  ("unlicensed") since the probe treats any non-`"0"` response code as a license
  failure. Confirmed against a real device: credentials/HMAC were valid the
  whole time, only the payload shape was wrong. Both fields are now strings,
  matching tr-people-finance's `hikcentral_query_window()` — the proven-working
  production caller of this same `/api/attendance/v1/report` endpoint —
  including its literal `" 04:00"` offset suffix (space, no `+`).

## [0.66.0] - 2026-08-16

### Fixed
- **SSRF guard added to `integrations/hikcentral.py`'s connect-time probes**
  (`hikcentral_get_version`, `hikcentral_probe_attendance`). Both made outbound
  HTTP calls to a tenant-admin-supplied `base_url` with zero address validation
  — found in adversarial security review of tr-crm-core#58/tr-people-finance#41,
  both consumers of this module. `_assert_safe_hikcentral_host` now resolves the
  host and rejects loopback, link-local (169.254.0.0/16 — cloud metadata, the #1
  SSRF target), multicast, and reserved/unspecified addresses before any request
  is issued. RFC1918/private-LAN ranges are deliberately still allowed —
  HikCentral devices are on-prem hardware, blocking private ranges would break
  the actual feature.

### v0.65.0 is a dead tag — do not pin to it
`v0.65.0` exists on this repo and will never be deleted (tags are frozen, see
root `CLAUDE.md`'s Upgrading Shared Libs section), but it points at
`b17568a` — a lockfile/formatting-only commit that **predates** the SSRF fix
above. It was cut by mistake against `main`'s tip before the fix branch had
been merged, discovered only when a consumer's relock produced a version
conflict with `shared-auth-lib`'s own pin. The fix was then properly merged to
`main` and re-tagged as `v0.66.0` — that is the first version that actually
contains it. If you're reading tag history and `v0.65.0` looks like the
natural pin, it is not: use `v0.66.0` or later.

## [0.63.0] - 2026-08-15

### Added
- **`TR_MIGRATIONS_SKIP_MERGE_CHECK`** — an explicit, opt-in escape hatch for
  `assert_migrations_are_merged` (`db/migrations/merge_gate.py`). A genuinely
  private, single-developer dev-tier database (e.g. a per-service Supabase
  project nobody else's checkout points at) is not the shared-mutable-state
  case the merge guard exists for, but its DSN is a real remote host, so
  `is_local_dsn` cannot recognise it — every history-writing `alembic
  upgrade`/`downgrade`/`stamp` against it was blocked until the revision
  existed on `origin/stage`, which forces a "push to the integration branch
  before you can test locally" ordering that doesn't fit a feature-branch
  workflow.

  Setting the flag skips the git comparison for that run. Mirrors
  `AUTH_LIB_DEV_MODE_BYPASS`'s (shared-auth-lib) own double-guard shape on
  purpose: the flag alone is not enough — `ENVIRONMENT` must also read as
  `development` or `test`, so a leftover flag is inert anywhere
  staging/production loads its real config, and every skip prints a warning
  naming the (redacted) DSN host so it is never silent. Read from
  `os.environ` directly rather than a settings object — the module has no
  framework dependency today, and importing one service's settings class
  here would create one for the other seven.

## [0.57.0] - 2026-08-03

### Removed
- **The Layer 2 DB-monitoring pipeline, in full.** `monitoring/persistence.py`
  (`PersistenceMiddleware`), `monitoring/redis_buffer.py`, `monitoring/models.py` (the
  `monitoring` schema's SQLAlchemy models) and the whole `monitoring/tasks/` package
  (`flush_monitoring_buffer`, `aggregate_hourly_metrics`, `aggregate_daily_metrics`,
  `create_next_day_partition`, `cleanup_old_monitoring_logs`).

  It never ran. Every entry point was gated on `MONITORING_DB_URL`, which was set in no
  `.env` and no `.env.example` anywhere in the workspace — so `enable_persistence` was
  always False and the five Celery tasks logged "skipping, not configured" on every tick,
  hourly, in four services. Prometheus + Grafana already covered the same ground; this was
  a second, unpopulated stack.

  **Breaking, but inertly so:** `setup_monitoring()` drops the `enable_persistence` and
  `redis_url` parameters, and its startup log line drops the `"persistence"` key. Every
  fleet caller passed `enable_persistence=bool(settings.MONITORING_DB_URL)` — i.e. `False` —
  and none reads the return value. All four callers were updated in the same change.
- `BaseServiceSettings.MONITORING_DB_URL` and `.MONITORING_ENABLED`. The first had one
  reader per service (the beat-schedule gate, now gone); the second had **zero readers
  fleet-wide** and was still being set to `"true"` in `docker-compose.dev.local.yml`.
- `monitoring/prometheus_client.py` (`PrometheusClient`). Not part of the Layer 2 stack —
  it queried live Prometheus over HTTP — but its sole consumer was crm-core's
  `system-monitoring` admin endpoint, deleted the same day. Zero importers remain.
  `prometheus_endpoint.py` (the `/metrics` mount) is untouched and unrelated.

`MetricsMiddleware`, the provider factory and adapters, `normalize_path`, `instruments`,
tracing, Loki, and the db/celery instrumentation are all unchanged.

## [0.56.0] - 2026-08-02

### Added
- `BaseAPIException` accepts `headers`, forwarded to `HTTPException`. Two subclasses already
  hand-rolled this — `RateLimitError` assigned `self.headers` after `super().__init__`, and
  content-platform's `CMSBaseException` did the same — because the base would not take it.
  Both now go through the base. `AuthenticationError` forwards `headers` so a 401 can carry
  the `WWW-Authenticate` challenge RFC 9110 §11.6.1 requires.

  This unblocked shared-auth-lib's authorization convergence: `auth_dependencies.py` is the
  fleet's only producer of `WWW-Authenticate`, and converting its raw `HTTPException` to the
  typed exception would have dropped the header silently — nothing asserted it there.

### Fixed
- `tr_shared.middleware` no longer imports `APIIdempotencyMiddleware` eagerly. It is the only
  member requiring the `redis` extra, so `from tr_shared.middleware import
  register_exception_handlers` raised `ModuleNotFoundError: redis` for any consumer without
  it — shared-auth-lib pins `[http,logging]` and so could not reach the error handlers every
  service is required to install. Now a lazy `__getattr__` export, matching
  `tr_shared.monitoring`'s db/celery instrumentation. Importing the name still works.
- Webhook endpoint errors emit the canonical envelope. Four responses answered with
  `{"error": "<string>"}` — `error` must always be an object — and carried no correlation id:
  rate-limited (`WEBHOOK_RATE_LIMIT_001`), invalid signature (`WEBHOOK_AUTH_001`), invalid
  JSON (`WEBHOOK_VALIDATION_001`) and failed Meta handshake (`WEBHOOK_AUTH_002`).

## [0.55.0] - 2026-08-01

### Added
- `tr_shared.config.log_unclaimed_env_keys(env_file=".env") -> list[str]` and
  `tr_shared.config.unclaimed_env_keys(env_file, classes=None) -> list[str]` — name the env
  keys no settings class declares. Every service's Settings is `extra="ignore"`, so a renamed
  or typo'd key is discarded silently; this is how a dev environment ended up pointed at
  production PropertyFinder. The collector unions every reachable `BaseSettings` subclass with
  `env_prefix` applied, excluding classes defined in test modules (see Fixed below), so
  `AUTH_LIB_*` and module-level settings are not reported as orphans.
- `tr_shared.testing.assert_no_orphan_env_keys(repo_root, *, extra_classes=())` — asserts
  every `.env.example` key has an owner: a settings field, or a name referenced in a compose
  file, Dockerfile, shell script or non-Python source. Runs on the committed template, not the
  gitignored `.env`, so it gates in CI rather than failing per-machine. Registered as **G15**
  in `docs/shared/TR_Testing_Standard.md` §10 (corrected post-release: originally logged here
  as G13, which was already taken by the shell environment-vocabulary guard).

### Fixed
- Error responses now surface `exc.headers`. `Retry-After` on a 429 and `WWW-Authenticate` on a
  401 were built by the raising code and then dropped by the handler. Transport-controlled
  headers (`content-length`, `content-type`, `transfer-encoding`, `connection`) are filtered
  out — a forged `Content-Length` is a request-smuggling primitive, not a header to pass on.
- Settings classes defined in test modules are excluded from owner auto-discovery. A fixture
  class that declared a key marked a genuinely-orphaned key as claimed — a false negative in
  the guard. Explicit `classes=` / `extra_classes=` are unaffected.
- The `.env.example` exemption scans `*.go` as well as compose/Dockerfile/shell. WAM's Go bot
  reads `WHATSMEOW_DB_PATH` and `CREWAI_BASE_URL` via `os.Getenv`; both were reported as
  orphans the guard told developers to delete.
- That same scan now skips `.worktrees` alongside `.venv`, `.git` and `node_modules`, matching
  `guards.iter_shell_files`. A worktree holds a copy of the repo at another revision, so a key
  consumed only on another branch could look claimed on this one.

### Changed
- **Breaking (no known consumers):** `reachable_settings_classes()` → `config_owner_classes()`,
  and `assert_env_example_is_declared()` → `assert_no_orphan_env_keys()`. Both were added in
  the unreleased range above and are renamed before first release: the first no longer returns
  everything reachable, and the second now matches the `assert_no_*` family used by every other
  guard in the testing standard's §10.

## [0.54.0] - 2026-08-01

### Added
- `tr_shared.phone.to_e164(value, default_region="AE") -> str | None` — normalizes a raw
  phone string to E.164 for a valid, plausibly-WhatsApp-reachable number, `None`
  otherwise. Never raises: unparseable, invalid, or non-mobile-reachable input (including
  landlines) all return `None`. Behind a new opt-in `phone` extra (`phonenumbers>=8.13.0`)
  so services that never touch phone data don't pull the dependency.

### Why
Owner-phone ingestion (DLD) needs one SSOT for turning free-text phone strings into a
dialable, WhatsApp-reachable format instead of each service re-implementing ad hoc
parsing. `to_e164` deliberately returns `None` for valid-but-non-mobile numbers such as
landlines — mobile-reachability is the intended semantics, not general E.164 conversion,
so a valid landline is treated the same as an invalid number by design.

### Migration
None. New opt-in extra — add `tr-shared-lib[phone]` (or the `phone` extra alongside your
existing extras) to pull in `phonenumbers`; services that don't need phone normalization
are unaffected.

## [0.53.0] - 2026-07-31

### Added
- **G14** — the pytest plugin now refuses to run when the interpreter belongs to a
  different service's `.venv` than the repo under test. Checked in
  `pytest_load_initial_conftests`, before any collection, and skipped entirely when the
  repo has no `.venv` (Docker images and CI install into the system environment).

### Why
Eight services sit side by side in this monorepo, each with its own `.venv`. Activate one
— or let an editor activate it — and `VIRTUAL_ENV` plus a `PATH` entry follow you into
every other service. `uv run pytest` there resolves the `pytest` executable out of the
*activated* venv, and the whole session imports from its `site-packages`.

Nothing announces this. It surfaces only where the two dependency sets happen to differ,
and then it lies: tr-people-finance reported **74 collection errors** for a missing
`email_validator` that was installed in its own venv the entire time, because the run was
using tr-media-service's, which does not depend on it. The only clue is the other
service's path inside the traceback, which is easy to read straight past — the obvious
reading is "a dependency is missing", and that sends you to fix something that was never
broken.

The guard belongs in the plugin rather than in eight `conftest.py` copies: every service
already loads it through the `pytest11` entry point, so there is no adoption gap and no
per-service list to keep current. Both paths are `resolve()`d before comparison, so a
symlinked checkout is not a false positive.

### Migration
None. A correctly-configured run never notices it. A run that trips it was already
broken — it now says so in one line naming both paths, instead of failing later as an
`ImportError` for a package that is present.

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
