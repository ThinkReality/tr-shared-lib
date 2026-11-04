"""
Supabase Vault access for per-tenant secrets a service creates at runtime.

:class:`VaultService` is create/read/update/delete of a single secret, session
injected by the caller::

    from tr_shared.vault import VaultService

    vault = VaultService(db_session)
    secret_id = await vault.create_secret(refresh_token, name=f"calendar:conn:{connection_id}")

Every :class:`VaultService` method raises on failure.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tr_shared.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_VAULT_TIMEOUT_SECONDS = 5.0

_T = TypeVar("_T")


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
        names, ``vault.secrets.name`` carries a unique index (``WHERE name IS NOT
        NULL``), and a stale row left by a partial write would otherwise make
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
            secret_id = cast("UUID", result.scalar_one())
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
