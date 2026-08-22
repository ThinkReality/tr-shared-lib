"""
Vault-backed secret resolution for ThinkRealty services.

At startup, for each entry in secret_map, looks up the Vault UUID from the
named env var and overwrites the settings field with the decrypted plaintext.
Empty UUID env var → silent skip (plain env var value remains).

Usage in lifespan()::

    from tr_shared.vault import resolve_vault_secrets

    async with AsyncSession(engine) as db:
        await resolve_vault_secrets(
            settings=settings,
            db_session=db,
            secret_map={
                "AUTH_LIB_GATEWAY_SIGNING_SECRET": "AUTH_LIB_GATEWAY_SIGNING_SECRET_VAULT_UUID",
                "AUTH_LIB_SERVICE_TOKEN": "AUTH_LIB_SERVICE_TOKEN_VAULT_UUID",
            },
        )

The write path is :class:`VaultService` — create/read/update/delete of a single
secret, session injected by the caller::

    from tr_shared.vault import VaultService

    vault = VaultService(db_session)
    secret_id = await vault.create_secret(refresh_token, name=f"calendar:conn:{connection_id}")

Unlike ``resolve_vault_secrets``, whose contract is "startup is never blocked",
every :class:`VaultService` method raises on failure.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tr_shared.exceptions import DatabaseError, ServiceUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_VAULT_TIMEOUT_SECONDS = 5.0

_T = TypeVar("_T")


async def resolve_vault_secrets(
    settings: object,
    db_session: AsyncSession,
    secret_map: dict[str, str],
) -> None:
    """Resolve Vault-backed secrets into a settings instance at startup.

    Empty/missing UUID env var skips silently — local-dev fallback keeps the
    plain env var value. Any error (bad UUID, DB failure, secret not found)
    leaves the field unchanged and logs a warning; startup is never blocked.
    """
    for field_name, uuid_env_var in secret_map.items():
        vault_uuid = os.environ.get(uuid_env_var, "").strip()
        if not vault_uuid:
            logger.debug(
                "Vault UUID env var %s not set; using plain env var for field %s",
                uuid_env_var,
                field_name,
            )
            continue

        try:
            uuid_obj = UUID(vault_uuid)
        except ValueError:
            logger.warning(
                "Invalid UUID value in env var %s: %r — skipping vault resolution for %s",
                uuid_env_var,
                vault_uuid,
                field_name,
            )
            continue

        try:
            result = await db_session.execute(
                text("SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = :secret_id"),
                {"secret_id": str(uuid_obj)},
            )
            row = result.fetchone()
        except Exception:
            logger.exception(
                "DB error while fetching vault secret for field %s (uuid=%s) — "
                "keeping plain env var value",
                field_name,
                vault_uuid,
            )
            continue

        if not row or not row[0]:
            logger.warning(
                "Vault secret not found for UUID %s (field %s) — keeping plain env var value",
                vault_uuid,
                field_name,
            )
            continue

        setattr(settings, field_name, row[0])
        logger.info(
            "Resolved vault secret for settings field %s (vault_uuid=%s)",
            field_name,
            vault_uuid,
        )


class VaultService:
    """Read/write access to a single Supabase Vault secret.

    Raw ``sqlalchemy.text()`` is unavoidable: the Vault extension exposes its
    interface only through PostgreSQL functions and the ``vault.decrypted_secrets``
    view, never through ORM models.

    The session is injected and never created here, so the secret write joins the
    caller's transaction and commits or rolls back with it.

    Every method runs under ``asyncio.wait_for``. The timeout is a constructor
    parameter rather than a settings read — a shared library cannot see a
    service's own config. **A ``ServiceUnavailableError`` means the statement was
    cancelled mid-flight: the session is no longer usable, so the caller must roll
    it back or discard it rather than issue further statements on it.**
    """

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        timeout_seconds: float = DEFAULT_VAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._db = db_session
        self._timeout = timeout_seconds

    async def create_secret(
        self,
        secret_value: str,
        name: str | None = None,
        description: str | None = None,
    ) -> UUID:
        """Store a new secret and return its id.

        A named secret is deleted first. Callers use deterministic per-entity
        names, ``vault.secrets.name`` carries a real (non-partial) unique
        constraint, and a stale row left by a partial write would otherwise make
        every future store under that name raise an unhandled ``IntegrityError``.
        Clearing first makes a retried write self-healing.
        """

        async def _op() -> UUID:
            if name:
                await self._db.execute(
                    text("DELETE FROM vault.secrets WHERE name = :name"),
                    {"name": name},
                )
            result = await self._db.execute(
                text("SELECT vault.create_secret(:secret, :name, :description) AS secret_id"),
                {"secret": secret_value, "name": name, "description": description or ""},
            )
            row = result.fetchone()
            if not row or not row[0]:
                raise DatabaseError(detail="Vault did not return a secret ID")
            secret_id = cast("UUID", row[0])
            logger.info("Vault secret created (vault_secret_id=%s)", secret_id)
            return secret_id

        return await self._guard(_op)

    async def read_secret(self, secret_id: UUID) -> str | None:
        """Return the decrypted secret, or ``None`` if no such row exists.

        A missing secret is not a database failure, so it is not an error here.
        """

        async def _op() -> str | None:
            result = await self._db.execute(
                text("SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = :secret_id"),
                {"secret_id": str(secret_id)},
            )
            row = result.fetchone()
            if not row:
                logger.warning("Vault secret not found (vault_secret_id=%s)", secret_id)
                return None
            return cast("str", row[0])

        return await self._guard(_op)

    async def update_secret(
        self,
        secret_id: UUID,
        new_secret: str,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        async def _op() -> None:
            await self._db.execute(
                text("SELECT vault.update_secret(:secret_id, :secret, :name, :description)"),
                {
                    "secret_id": str(secret_id),
                    "secret": new_secret,
                    "name": name,
                    "description": description,
                },
            )
            logger.info("Vault secret updated (vault_secret_id=%s)", secret_id)

        await self._guard(_op)

    async def delete_secret(self, secret_id: UUID) -> None:
        async def _op() -> None:
            await self._db.execute(
                text("DELETE FROM vault.secrets WHERE id = :secret_id"),
                {"secret_id": str(secret_id)},
            )
            logger.info("Vault secret deleted (vault_secret_id=%s)", secret_id)

        await self._guard(_op)

    async def _guard(self, op: Callable[[], Awaitable[_T]]) -> _T:
        try:
            return await asyncio.wait_for(op(), timeout=self._timeout)
        except TimeoutError as exc:
            raise ServiceUnavailableError(detail="Vault operation timed out") from exc
