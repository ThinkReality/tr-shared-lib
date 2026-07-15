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
"""

import logging
import os
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
                text(
                    "SELECT decrypted_secret "
                    "FROM vault.decrypted_secrets "
                    "WHERE id = :secret_id"
                ),
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
                "Vault secret not found for UUID %s (field %s) — "
                "keeping plain env var value",
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
