from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tr_shared.exceptions import ServiceUnavailableError
from tr_shared.vault import DEFAULT_VAULT_TIMEOUT_SECONDS, VaultService, resolve_vault_secrets

pytestmark = pytest.mark.integration


class _Settings:
    API_KEY = "plain-env-value"


@pytest_asyncio.fixture
async def engine(postgres_dsn: str):
    engine = create_async_engine(postgres_dsn, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield AsyncSession(bind=conn)
        await transaction.rollback()


async def _name_and_description(db: AsyncSession, secret_id: uuid.UUID) -> tuple:
    result = await db.execute(
        text("SELECT name, description FROM vault.secrets WHERE id = :id"), {"id": secret_id}
    )
    return tuple(result.one())


async def test_a_created_secret_reads_back_as_plaintext(db) -> None:
    vault = VaultService(db)

    secret_id = await vault.create_secret("refresh-token", name=f"probe:{uuid.uuid4()}")

    assert await vault.read_secret(secret_id) == "refresh-token"


async def test_creating_under_a_taken_name_replaces_the_old_secret(db) -> None:
    vault = VaultService(db)
    name = f"probe:{uuid.uuid4()}"
    stale_id = await vault.create_secret("stale-token", name=name)

    fresh_id = await vault.create_secret("fresh-token", name=name)

    assert await vault.read_secret(stale_id) is None
    assert await vault.read_secret(fresh_id) == "fresh-token"


async def test_reading_an_unknown_secret_returns_none(db) -> None:
    assert await VaultService(db).read_secret(uuid.uuid4()) is None


async def test_update_replaces_the_value_and_keeps_name_and_description(db) -> None:
    vault = VaultService(db)
    name = f"probe:{uuid.uuid4()}"
    secret_id = await vault.create_secret("old-token", name=name, description="google calendar")

    await vault.update_secret(secret_id, "new-token")

    assert await vault.read_secret(secret_id) == "new-token"
    assert await _name_and_description(db, secret_id) == (name, "google calendar")


async def test_delete_removes_the_secret(db) -> None:
    vault = VaultService(db)
    secret_id = await vault.create_secret("refresh-token")

    await vault.delete_secret(secret_id)

    assert await vault.read_secret(secret_id) is None


async def test_a_write_rolls_back_with_the_callers_transaction(engine) -> None:
    async with AsyncSession(engine) as session:
        secret_id = await VaultService(session).create_secret("refresh-token")
        await session.rollback()

    async with AsyncSession(engine) as session:
        assert await VaultService(session).read_secret(secret_id) is None


@pytest.mark.parametrize(
    "method,args",
    [
        ("create_secret", ("token", "probe:locked")),
        ("read_secret", (uuid.uuid4(),)),
        ("update_secret", (uuid.uuid4(), "token")),
        ("delete_secret", (uuid.uuid4(),)),
    ],
)
async def test_a_blocked_statement_times_out_as_service_unavailable(engine, method, args) -> None:
    async with engine.connect() as locker:
        await locker.begin()
        await locker.execute(text("LOCK TABLE vault.secrets IN ACCESS EXCLUSIVE MODE"))
        async with AsyncSession(engine) as session:
            with pytest.raises(ServiceUnavailableError) as exc:
                await getattr(VaultService(session, timeout_seconds=0.5), method)(*args)

    assert exc.value.error_code == "SERVICE_UNAVAILABLE_001"


async def test_startup_replaces_the_setting_with_the_vault_secret(db, monkeypatch) -> None:
    secret_id = await VaultService(db).create_secret("vault-value")
    monkeypatch.setenv("API_KEY_VAULT_UUID", str(secret_id))
    settings = _Settings()

    await resolve_vault_secrets(settings, db, {"API_KEY": "API_KEY_VAULT_UUID"})

    assert settings.API_KEY == "vault-value"


@pytest.mark.parametrize("vault_uuid", ["", "not-a-uuid", str(uuid.uuid4())])
async def test_startup_keeps_the_plain_value_when_the_vault_has_none(
    db, monkeypatch, vault_uuid
) -> None:
    monkeypatch.setenv("API_KEY_VAULT_UUID", vault_uuid)
    settings = _Settings()

    await resolve_vault_secrets(settings, db, {"API_KEY": "API_KEY_VAULT_UUID"})

    assert settings.API_KEY == "plain-env-value"


async def test_startup_keeps_the_plain_value_when_the_vault_read_hangs(engine, monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_VAULT_UUID", str(uuid.uuid4()))
    settings = _Settings()

    async with engine.connect() as locker:
        await locker.begin()
        await locker.execute(text("LOCK TABLE vault.secrets IN ACCESS EXCLUSIVE MODE"))
        async with AsyncSession(engine) as session:
            await asyncio.wait_for(
                resolve_vault_secrets(settings, session, {"API_KEY": "API_KEY_VAULT_UUID"}),
                timeout=DEFAULT_VAULT_TIMEOUT_SECONDS + 5,
            )

    assert settings.API_KEY == "plain-env-value"


class _TwoSecrets:
    API_KEY = "plain-env-value"
    OTHER_KEY = "plain-other-value"


async def test_a_hung_read_does_not_cost_the_next_field_its_secret(engine, monkeypatch) -> None:
    async with AsyncSession(engine) as setup:
        stored_id = await VaultService(setup).create_secret("vault-value")
        await setup.commit()
    monkeypatch.setenv("API_KEY_VAULT_UUID", str(uuid.uuid4()))
    monkeypatch.setenv("OTHER_KEY_VAULT_UUID", str(stored_id))
    settings = _TwoSecrets()

    async with engine.connect() as locker:
        await locker.begin()
        await locker.execute(text("LOCK TABLE vault.secrets IN ACCESS EXCLUSIVE MODE"))
        async with AsyncSession(engine) as session:
            hung = asyncio.create_task(
                resolve_vault_secrets(
                    settings,
                    session,
                    {"API_KEY": "API_KEY_VAULT_UUID", "OTHER_KEY": "OTHER_KEY_VAULT_UUID"},
                )
            )
            await asyncio.sleep(DEFAULT_VAULT_TIMEOUT_SECONDS + 1)
            await locker.rollback()
            await asyncio.wait_for(hung, timeout=DEFAULT_VAULT_TIMEOUT_SECONDS + 5)

    async with AsyncSession(engine) as cleanup:
        await VaultService(cleanup).delete_secret(stored_id)
        await cleanup.commit()

    assert settings.API_KEY == "plain-env-value"
    assert settings.OTHER_KEY == "vault-value"


async def test_startup_keeps_the_plain_value_when_the_database_is_down(
    postgres_dsn, monkeypatch
) -> None:
    unreachable = create_async_engine(make_url(postgres_dsn).set(port=1), poolclass=NullPool)
    monkeypatch.setenv("API_KEY_VAULT_UUID", str(uuid.uuid4()))
    settings = _Settings()

    async with AsyncSession(unreachable) as session:
        await resolve_vault_secrets(settings, session, {"API_KEY": "API_KEY_VAULT_UUID"})
    await unreachable.dispose()

    assert settings.API_KEY == "plain-env-value"
