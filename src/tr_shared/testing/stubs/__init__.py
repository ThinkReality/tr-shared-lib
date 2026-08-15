"""Shared third-party test fakes.

Only built for integrations with REAL cross-service duplication — verified by
reading, not assumed. PropertyFinder and Bayut are each hand-mocked independently
in three services today (crm-core, content-platform, lead-management), with three
genuinely different mocking mechanics (``httpx.MockTransport``, patched client
internals, patched ``httpx.AsyncClient``). Supabase, Gemini and SuprSend remain
single-service or non-existent stubs — no duplication to remove, so nothing is
built here for them; adding fakes with nothing to deduplicate would be speculative.

HikCentral is the exception as of the per-tenant integration
(plans/2026-08-15-hikcentral-per-tenant-integration.md): tr-crm-core's
``HikCentralRegistrar`` (connect-flow validation) and tr-people-finance's
``HikCentralAPI`` (HR domain client) both call the same two HTTP endpoints
through the shared ``tr_shared.integrations.hikcentral`` signing functions —
real, planned duplication, not speculative.

``MockTransportBuilder`` (``http_stub.py``) is the one real mechanism this module
standardizes on: it drives the actual ``httpx.AsyncClient``/``httpx.Client`` a
service's production code already uses, rather than patching internals — the same
approach as the most realistic of the three styles already in the fleet.

Submodules import ``httpx`` lazily (not a core ``tr_shared`` dependency) — import
what you need directly, e.g. ``from tr_shared.testing.stubs.propertyfinder import
PropertyFinderStub``, rather than from this package's own namespace.
"""
