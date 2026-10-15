from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.testing import admin_database_url
from tr_shared.testing.config import TestingConfig, find_config
from tr_shared.testing.stack import create_run_database, drop_run_databases, provision

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(not _docker_available(), reason="Docker is not reachable")


def _config(tmp_path: Path) -> TestingConfig:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0'\n\n"
        "[tool.tr_testing]\n"
        "service = 'tr-parity-demo'\n"
        f"migrate_command = [{sys.executable!r}, '-c', 'pass']\n"
        "migration_globs = ['migrations/*.sql']\n"
    )
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001.sql").write_text(f"-- {tmp_path.name}\n")
    config = find_config(tmp_path)
    assert config is not None
    return config


async def _vault_survives_an_admin_rename(dsn: str) -> tuple[str, str]:
    admin = create_async_engine(admin_database_url(dsn), poolclass=NullPool)
    app = create_async_engine(dsn, poolclass=NullPool)
    signature = "vault.%s(text, text, text, uuid)"
    try:
        async with admin.begin() as conn:
            await conn.execute(
                text(f"ALTER FUNCTION {signature % 'create_secret'} RENAME TO create_secret_down")
            )
        try:
            async with app.begin() as conn:
                await conn.scalar(text("SELECT vault.create_secret('down')"))
            failure = "none"
        except DBAPIError as exc:
            failure = str(exc)
        async with admin.begin() as conn:
            await conn.execute(
                text(f"ALTER FUNCTION {signature % 'create_secret_down'} RENAME TO create_secret")
            )
        async with app.begin() as conn:
            secret_id = await conn.scalar(text("SELECT vault.create_secret('back')"))
        async with app.connect() as conn:
            restored = await conn.scalar(
                text("SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = :id"),
                {"id": secret_id},
            )
        return failure, restored
    finally:
        await admin.dispose()
        await app.dispose()


async def _observe(dsn: str) -> dict[str, object]:
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            secret_id = await conn.scalar(text("SELECT vault.create_secret('s3cret', 'parity')"))
        async with engine.connect() as conn:
            return {
                "version": await conn.scalar(text("SHOW server_version")),
                "role": (
                    await conn.execute(
                        text(
                            "SELECT current_user, rolsuper, "
                            "pg_get_userbyid(d.datdba) = current_user "
                            "FROM pg_roles, pg_database d "
                            "WHERE rolname = current_user AND d.datname = current_database()"
                        )
                    )
                ).one(),
                "extensions": dict(
                    (
                        await conn.execute(
                            text(
                                "SELECT extname, extnamespace::regnamespace::text FROM pg_extension "
                                "WHERE extname <> 'plpgsql'"
                            )
                        )
                    ).all()
                ),
                "stored_encrypted": await conn.scalar(
                    text("SELECT secret <> 's3cret' FROM vault.secrets WHERE id = :id"),
                    {"id": secret_id},
                ),
                "decrypted": await conn.scalar(
                    text("SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = :id"),
                    {"id": secret_id},
                ),
            }
    finally:
        await engine.dispose()


@requires_docker
def test_a_run_database_looks_like_the_staging_database(tmp_path: Path) -> None:
    config = _config(tmp_path)
    try:
        stack = provision(config, "parity", "gw0")
        create_run_database(config, "parity", "gw0")
        seen = asyncio.run(_observe(stack.postgres_dsn))
        failure, restored = asyncio.run(_vault_survives_an_admin_rename(stack.postgres_dsn))
    finally:
        drop_run_databases(config, "parity", "gw0")
        for kind in ("pg", "redis"):
            subprocess.run(
                ["docker", "rm", "-f", f"tr-test-{kind}-{config.key[:10]}"],
                capture_output=True,
                text=True,
            )

    assert str(seen["version"]).startswith("17.6")
    assert tuple(seen["role"]) == ("postgres", False, True)
    assert seen["extensions"] == {
        "pgcrypto": "extensions",
        "uuid-ossp": "extensions",
        "pg_trgm": "public",
        "supabase_vault": "vault",
    }
    assert seen["stored_encrypted"] is True
    assert seen["decrypted"] == "s3cret"
    assert "function vault.create_secret(unknown) does not exist" in failure
    assert restored == "back"


@requires_docker
def test_a_fresh_container_counts_as_ready_only_once_its_final_server_is_up(
    tmp_path: Path,
) -> None:
    from tr_shared.testing.stack import (
        _POSTGRES_ENVIRONMENT,
        _POSTGRES_READY_PROBE,
        _docker,
        _ensure_container,
    )

    name = f"tr-test-ready-{tmp_path.name[-12:].lower()}"
    client = _docker()
    try:
        _ensure_container(
            client,
            name=name,
            image=_config(tmp_path).postgres_image,
            container_port=5432,
            environment=_POSTGRES_ENVIRONMENT,
            command=None,
            ready_probe=_POSTGRES_READY_PROBE,
        )
        logs = client.containers.get(name).logs().decode(errors="replace")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)

    assert 'listening on IPv4 address "0.0.0.0", port 5432' in logs
