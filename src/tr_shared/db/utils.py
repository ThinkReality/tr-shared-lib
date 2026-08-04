"""Database utilities: Supavisor URL conversion + SQL query helpers."""

from urllib.parse import urlparse, urlsplit, urlunparse

LIKE_ESCAPE_CHAR = "\\"

LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "postgres-test", "db"})
"""Hosts that count as a database on this machine.

SSOT for a question two guards ask: the testing plugin's G1 check (a non-local
TEST DSN is a hard failure, never a skip) and the migration merge gate (an
unmerged revision may not reach a non-local database). Restating it in either
place is how the two drift apart.
"""

LOCAL_DB_HOST_PREFIX = "tr-test-"
"""Prefix of the testcontainers-provisioned Postgres used by the integration lane."""


def is_local_dsn(dsn: str) -> bool:
    """Whether *dsn* points at a database on this machine.

    A DSN that cannot be parsed returns ``False``. Both callers use this to
    decide whether a destructive action is permitted, so unknown must never read
    as safe.
    """
    try:
        host = (urlsplit(dsn).hostname or "").lower()
    except ValueError:
        return False
    return host in LOCAL_DB_HOSTS or host.startswith(LOCAL_DB_HOST_PREFIX)


def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcards (``%`` ``_`` ``\\``) in user search terms.

    Pair with an explicit escape char so the escapes are honoured::

        col.ilike(f"%{escape_like(term)}%", escape="\\\\")

    Without this, a user-supplied ``%`` or ``_`` is treated as a wildcard
    (e.g. searching ``"50%"`` would match every row).
    """
    return (
        value.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
        .replace("%", LIKE_ESCAPE_CHAR + "%")
        .replace("_", LIKE_ESCAPE_CHAR + "_")
    )


def to_session_mode_url(url: str) -> str:
    """Swap port 6543 (Transaction mode) to 5432 (Session mode).

    Supabase Supavisor uses:
      - port 6543 = Transaction mode (app traffic)
      - port 5432 = Session mode (migrations, DDL)

    Both ports work on the same pooler host.
    If the URL doesn't use port 6543, returns it unchanged.
    """
    parsed = urlparse(url)
    if parsed.port == 6543:
        netloc = parsed.netloc.replace(":6543", ":5432", 1)
        return urlunparse(parsed._replace(netloc=netloc))
    return url


def to_sync_url(url: str) -> str:
    """Convert async/legacy driver URL to sync driver for Alembic.

    postgres:// → postgresql+psycopg2://  (Railway legacy scheme)
    postgresql+asyncpg:// → postgresql+psycopg2://
    postgresql:// → postgresql+psycopg2://

    .. deprecated::
        The platform is standardising on a single asyncpg driver for both
        runtime and migrations. New/migrated services should use
        ``run_async_migrations`` (async Alembic) instead of this sync-psycopg2
        path. Retained for services not yet converted.
    """
    url = url.replace("postgres://", "postgresql://", 1)
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def to_migration_url(url: str) -> str:
    """Convert a DATABASE_URL to a migration-safe URL.

    1. Swaps to Session mode (port 5432) for DDL support
    2. Converts to sync driver for Alembic

    Usage in alembic/env.py:
        from tr_shared.db.utils import to_migration_url
        url = to_migration_url(os.getenv("DATABASE_URL", ""))

    .. deprecated::
        Forces the sync psycopg2 driver. The platform is standardising on a
        single asyncpg driver — new/migrated services should use
        ``run_async_migrations`` (async Alembic) + ``to_session_mode_url``
        instead. Retained for services not yet converted.
    """
    return to_sync_url(to_session_mode_url(url))
