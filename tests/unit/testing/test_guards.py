"""Each guard fires on the real violation and stays quiet on the correct form.

Every "bad" sample below is taken from code that actually shipped in this
monorepo, not invented. A guard that only catches a contrived example is a guard
that will not catch the next real one — and two guards in this repo have already
failed exactly that way: one matched prose in a docstring, and one was worded so
that the 28 files it existed to catch passed it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tr_shared.testing.guards import (
    Exemption,
    assert_no_auth_chain_bypass,
    assert_no_env_mutation_in_conftest,
    assert_no_infra_skips,
    assert_no_ryuk_disabled,
    assert_no_schema_construction,
    assert_no_sqlite_dsn,
    assert_no_testing_flag_in_production,
    detect_auth_chain_bypass,
    detect_env_mutation,
    detect_schema_construction,
    detect_sqlite_dsn,
    detect_testing_flag,
)


def _tree(tmp_path: Path, name: str, source: str) -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)
    return tmp_path


class TestG2Sqlite:
    def test_catches_the_real_fixture(self) -> None:
        # tr-crm-core/tests/admin/conftest.py:33, and WAM's conftest.
        assert detect_sqlite_dsn('engine = create_async_engine("sqlite+aiosqlite:///:memory:")')
        assert detect_sqlite_dsn('os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"')

    def test_ignores_postgres(self) -> None:
        assert not detect_sqlite_dsn('create_async_engine("postgresql+asyncpg://u:p@h/db")')

    def test_ignores_the_word_in_prose(self) -> None:
        assert not detect_sqlite_dsn('"""SQLite is unusable here — needs real PG."""')

    def test_assert_helper_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "conftest.py", 'URL = "sqlite+aiosqlite:///:memory:"')
        with pytest.raises(AssertionError, match="sqlite DSN"):
            assert_no_sqlite_dsn(root)


class TestG5AuthChain:
    def test_catches_dependency_overrides(self) -> None:
        """The form that made an earlier guard useless — 28 files used it."""
        assert detect_auth_chain_bypass(
            "app.dependency_overrides[require_auth] = lambda: ctx"
        )
        assert detect_auth_chain_bypass(
            "app.dependency_overrides[optional_auth] = lambda: None"
        )

    def test_catches_the_middleware_monkeypatch(self) -> None:
        # tr-lead-management/tests/integration/conftest.py:27
        assert detect_auth_chain_bypass(
            "GatewayHMACMiddleware.dispatch = _passthrough_dispatch"
        )

    def test_catches_monkeypatch_setattr(self) -> None:
        assert detect_auth_chain_bypass(
            'monkeypatch.setattr(GatewayHMACMiddleware, "dispatch", _passthrough)'
        )

    def test_catches_the_bypass_flag(self) -> None:
        assert detect_auth_chain_bypass(
            'os.environ["AUTH_LIB_DEV_MODE_BYPASS"] = "true"'
        )

    def test_allows_the_sanctioned_helper(self) -> None:
        """signed_client runs every real layer, so it must not trip the guard."""
        assert not detect_auth_chain_bypass(
            "from shared_auth_lib.testing import Persona, signed_client\n"
            "client = signed_client(app, Persona(permissions=('a',)))"
        )

    def test_allows_overriding_unrelated_dependencies(self) -> None:
        assert not detect_auth_chain_bypass(
            "app.dependency_overrides[get_session] = _override"
        )

    def test_assert_helper_fails(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path, "integration/conftest.py",
            "GatewayHMACMiddleware.dispatch = _passthrough",
        )
        with pytest.raises(AssertionError, match="auth chain"):
            assert_no_auth_chain_bypass(root)


class TestG7SchemaConstruction:
    def test_catches_create_all_called_and_passed(self) -> None:
        assert detect_schema_construction("await conn.run_sync(Base.metadata.create_all)")
        assert detect_schema_construction("Base.metadata.create_all(bind=engine)")

    def test_catches_drop_schema_in_a_call(self) -> None:
        assert detect_schema_construction(
            'await conn.execute(text("DROP SCHEMA IF EXISTS auth_schema CASCADE"))'
        )

    def test_catches_the_alembic_python_api(self) -> None:
        """Text matching cannot see this — "upgrade head" never appears."""
        assert detect_schema_construction('command.upgrade(cfg, "head")')

    def test_ignores_prose_that_lowercases_into_the_pattern(self) -> None:
        """The exact false positive that made the first version unusable."""
        assert not detect_schema_construction(
            '"""Tests for CredentialTypeCreate schema."""'
        )
        assert not detect_schema_construction('"""Drops schema residue between runs."""')

    def test_assert_helper_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "auth/conftest.py", "conn.run_sync(Base.metadata.create_all)")
        with pytest.raises(AssertionError, match="Schema construction"):
            assert_no_schema_construction(root)

    def test_exemption_must_be_machine_checkable(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "migrations/conftest.py", 'command.upgrade(cfg, "head")')
        with pytest.raises(AssertionError, match="prose alone"):
            assert_no_schema_construction(
                root, {"migrations/conftest.py": Exemption(reason="it is fine, trust me")}
            )

    def test_exemption_is_rejected_when_its_proof_vanishes(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "migrations/conftest.py", 'command.upgrade(cfg, "head")')
        with pytest.raises(AssertionError, match="no longer in the module"):
            assert_no_schema_construction(
                root,
                {
                    "migrations/conftest.py": Exemption(
                        reason="throwaway roundtrip database, never the shared one",
                        requires_symbols=("_roundtrip",),
                    )
                },
            )

    def test_valid_exemption_passes(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path,
            "migrations/conftest.py",
            '_roundtrip = True\ncommand.upgrade(cfg, "head")',
        )
        assert_no_schema_construction(
            root,
            {
                "migrations/conftest.py": Exemption(
                    reason="throwaway roundtrip database, never the shared one",
                    requires_symbols=("_roundtrip",),
                )
            },
        )

    def test_stale_exemption_is_rejected(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "clean/conftest.py", "x = 1")
        with pytest.raises(AssertionError, match="no longer violate"):
            assert_no_schema_construction(
                root,
                {"clean/conftest.py": Exemption(reason="x" * 70, requires_symbols=("x",))},
            )


class TestG9EnvMutation:
    def test_catches_assignment_and_setdefault(self) -> None:
        assert detect_env_mutation('os.environ["DATABASE_URL"] = url')
        assert detect_env_mutation('os.environ.setdefault("DATABASE_URL", url)')

    def test_ignores_unrelated_variables(self) -> None:
        assert not detect_env_mutation('os.environ["SERVICE_NAME"] = "tr-demo"')

    def test_ignores_reads(self) -> None:
        assert not detect_env_mutation('url = os.environ["DATABASE_URL"]')

    def test_assert_helper_only_looks_at_conftests(self, tmp_path: Path) -> None:
        (tmp_path / "unit").mkdir()
        (tmp_path / "unit" / "test_x.py").write_text('os.environ["DATABASE_URL"] = "x"')
        assert_no_env_mutation_in_conftest(tmp_path)  # not a conftest -> ignored

        (tmp_path / "conftest.py").write_text('os.environ["DATABASE_URL"] = "x"')
        with pytest.raises(AssertionError, match="infrastructure environment"):
            assert_no_env_mutation_in_conftest(tmp_path)


class TestG10Ryuk:
    def test_catches_the_real_line(self, tmp_path: Path) -> None:
        # tr-crm-core/tests/task/integration/conftest.py:6
        root = _tree(
            tmp_path,
            "task/conftest.py",
            'os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")',
        )
        with pytest.raises(AssertionError, match="process-global"):
            assert_no_ryuk_disabled(root)


class TestG11InfraSkips:
    def test_catches_the_real_skips(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path,
            "api/conftest.py",
            'pytest.skip(f"API harness infra unavailable: {exc}")',
        )
        with pytest.raises(AssertionError, match="green"):
            assert_no_infra_skips(root)

    def test_allows_a_legitimate_skip(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path, "unit/test_x.py", 'pytest.skip("only meaningful on Windows")'
        )
        assert_no_infra_skips(root)


class TestG12TestingFlag:
    def test_catches_the_real_flag(self) -> None:
        # tr-whatsApp-marketing-agent/app/core/rate_limiting.py:40
        assert detect_testing_flag("if get_settings().TESTING:\n    return")
        assert detect_testing_flag('if os.environ.get("PYTEST_CURRENT_TEST"):\n    pass')

    def test_ignores_unrelated_attributes(self) -> None:
        assert not detect_testing_flag("if settings.RATE_LIMIT_ENABLED:\n    pass")

    def test_assert_helper_fails(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "core/rate_limiting.py", "if get_settings().TESTING:\n    pass")
        with pytest.raises(AssertionError, match="branching on being under test"):
            assert_no_testing_flag_in_production(root)

    def test_migrations_are_not_scanned(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, "alembic/versions/0001.py", "TESTING = 1")
        assert_no_testing_flag_in_production(root)
