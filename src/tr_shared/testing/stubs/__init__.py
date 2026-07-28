"""Shared third-party test fakes.

Only built for integrations with REAL cross-service duplication — verified by
reading, not assumed. PropertyFinder and Bayut are each hand-mocked independently
in three services today (crm-core, content-platform, lead-management), with three
genuinely different mocking mechanics (``httpx.MockTransport``, patched client
internals, patched ``httpx.AsyncClient``). Supabase, Gemini, HikCentral and SuprSend
are single-service or non-existent stubs — no duplication to remove, so nothing is
built here for them; adding fakes with nothing to deduplicate would be speculative.

``MockTransportBuilder`` (``http_stub.py``) is the one real mechanism this module
standardizes on: it drives the actual ``httpx.AsyncClient``/``httpx.Client`` a
service's production code already uses, rather than patching internals — the same
approach as the most realistic of the three styles already in the fleet.

Submodules import ``httpx`` lazily (not a core ``tr_shared`` dependency) — import
what you need directly, e.g. ``from tr_shared.testing.stubs.propertyfinder import
PropertyFinderStub``, rather than from this package's own namespace.
"""
