"""The fleet tenant-header scanner must resist ordinary refactors, not just literals.

Every service test that uses this helper is only as good as the matcher, so the
matcher is tested here once rather than duplicated eight times.
"""

from __future__ import annotations

import textwrap

import pytest

from tr_shared.testing import (
    Exemption,
    assert_exemptions_are_machine_verified,
    assert_no_stale_exemptions,
    assert_no_undocumented_raw_tenant_header_reads,
    find_raw_tenant_header_readers,
    scan_source_for_raw_tenant_header_reads,
)


def _hits(src: str) -> list[int]:
    return scan_source_for_raw_tenant_header_reads(textwrap.dedent(src))


class TestMatcherResistsRefactorEvasions:
    def test_catches_direct_read(self):
        assert _hits('t = request.headers.get("x-tenant-id")')

    def test_is_case_insensitive_on_the_header_name(self):
        assert _hits('t = request.headers.get("X-Tenant-ID")')

    def test_catches_headers_pulled_into_a_variable(self):
        assert _hits("""
            headers = request.headers
            t = headers.get("x-tenant-id")
        """)

    def test_catches_header_name_in_a_constant(self):
        assert _hits("""
            KEY = "x-tenant-id"
            t = request.headers.get(KEY)
        """)

    def test_catches_both_evasions_combined(self):
        assert _hits("""
            KEY = "x-tenant-id"
            headers = dict(request.headers)
            t = headers.get(KEY)
        """)

    def test_catches_subscript_form(self):
        assert _hits('t = request.headers["x-tenant-id"]')

    def test_catches_enum_key_with_and_without_dot_value(self):
        assert _hits("t = request.headers.get(HttpHeader.TENANT_ID.value)")
        assert _hits("t = request.headers.get(GatewayHeaders.TENANT_ID)")

    def test_catches_fastapi_header_param(self):
        assert _hits('def f(x: str = Header(..., alias="x-tenant-id")): ...')

    def test_catches_normalised_enum_key(self):
        """``.value.lower()`` is the CORRECT thing to write — ASGI lowercases keys.

        Missing this form is not a theoretical gap: it is why an earlier version
        of this scanner reported tr-lead-management as having zero raw reads,
        when its webhook ingestion resolves the tenant that exact way.
        """
        assert _hits('t = request.headers.get("X-Tenant-ID".lower())')
        assert _hits("t = request.headers.get(HttpHeader.TENANT_ID.value.strip().lower())")

    def test_catches_a_headers_mapping_passed_as_a_parameter(self):
        """The real lead-management shape: resolution extracted into a helper."""
        assert _hits("""
            def _resolve_tenant(provider, headers, payload):
                return headers.get(HttpHeader.TENANT_ID.value.lower()) or None
        """)

    def test_catches_a_suffixed_headers_parameter(self):
        assert _hits("""
            def handle(inbound_headers):
                return inbound_headers["x-tenant-id"]
        """)

    def test_ignores_outbound_client_headers(self):
        """Building a headers dict to SEND asserts nothing about the caller."""
        assert not _hits('await client.get(url, headers={"x-tenant-id": str(tenant_id)})')

    def test_ignores_unrelated_headers(self):
        assert not _hits('t = request.headers.get("x-correlation-id")')


class TestAssertions:
    @pytest.fixture
    def app_root(self, tmp_path):
        root = tmp_path / "app"
        (root / "api").mkdir(parents=True)
        (root / "alembic" / "versions").mkdir(parents=True)
        return root

    def test_reader_is_found_and_reported_relative(self, app_root):
        (app_root / "api" / "handler.py").write_text('t = request.headers.get("x-tenant-id")\n')

        assert find_raw_tenant_header_readers(app_root) == {"api/handler.py": [1]}

    def test_a_byte_order_mark_does_not_crash_the_scan(self, app_root):
        """A BOM makes ast.parse raise, and a crashing guard is an absent guard."""
        (app_root / "api" / "handler.py").write_text(
            '﻿import hashlib\nt = request.headers.get("x-tenant-id")\n', encoding="utf-8"
        )

        assert find_raw_tenant_header_readers(app_root) == {"api/handler.py": [2]}

    def test_migrations_are_skipped(self, app_root):
        (app_root / "alembic" / "versions" / "m.py").write_text(
            't = request.headers.get("x-tenant-id")\n'
        )

        assert find_raw_tenant_header_readers(app_root) == {}

    def test_undocumented_reader_fails(self, app_root):
        (app_root / "api" / "handler.py").write_text('t = request.headers.get("x-tenant-id")\n')

        with pytest.raises(AssertionError, match="New raw X-Tenant-ID read"):
            assert_no_undocumented_raw_tenant_header_reads(app_root, {})

    def test_allowlisted_reader_passes(self, app_root):
        (app_root / "api" / "handler.py").write_text('t = request.headers.get("x-tenant-id")\n')

        assert_no_undocumented_raw_tenant_header_reads(
            app_root,
            {"api/handler.py": Exemption(reason="x" * 61, requires_symbols=())},
        )

    def test_stale_allowlist_entry_fails(self, app_root):
        (app_root / "api" / "handler.py").write_text("t = 1\n")

        with pytest.raises(AssertionError, match="no longer read the header"):
            assert_no_stale_exemptions(app_root, {"api/handler.py": Exemption(reason="x" * 61)})

    def test_exemption_with_only_prose_fails(self, app_root):
        (app_root / "api" / "handler.py").write_text('t = request.headers.get("x-tenant-id")\n')

        with pytest.raises(AssertionError, match="rests on prose alone"):
            assert_exemptions_are_machine_verified(
                app_root, {"api/handler.py": Exemption(reason="x" * 61)}
            )

    def test_exemption_fails_when_its_gating_symbol_disappears(self, app_root):
        (app_root / "api" / "handler.py").write_text('t = request.headers.get("x-tenant-id")\n')

        with pytest.raises(AssertionError, match="the gate its exemption depends on is gone"):
            assert_exemptions_are_machine_verified(
                app_root,
                {
                    "api/handler.py": Exemption(
                        reason="x" * 61, requires_symbols=("validate_service_token",)
                    )
                },
            )

    def test_exemption_passes_while_its_gating_symbol_is_present(self, app_root):
        (app_root / "api" / "handler.py").write_text(
            "from app.core.auth import validate_service_token\n"
            't = request.headers.get("x-tenant-id")\n'
        )

        assert_exemptions_are_machine_verified(
            app_root,
            {
                "api/handler.py": Exemption(
                    reason="x" * 61, requires_symbols=("validate_service_token",)
                )
            },
        )

    def test_inert_exemption_fails_once_the_module_reaches_data(self, app_root):
        (app_root / "api" / "handler.py").write_text(
            "from app.repositories.lead_repository import LeadRepository\n"
            't = request.headers.get("x-tenant-id")\n'
        )

        with pytest.raises(AssertionError, match="exempt only while it is inert"):
            assert_exemptions_are_machine_verified(
                app_root,
                {"api/handler.py": Exemption(reason="x" * 61, must_be_inert=True)},
            )

    def test_inert_exemption_passes_for_a_stub(self, app_root):
        (app_root / "api" / "handler.py").write_text(
            'import logging\nt = request.headers.get("x-tenant-id")\n'
        )

        assert_exemptions_are_machine_verified(
            app_root, {"api/handler.py": Exemption(reason="x" * 61, must_be_inert=True)}
        )
