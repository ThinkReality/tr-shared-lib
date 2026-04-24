"""Database URL utilities for Supavisor compatibility."""

from urllib.parse import urlparse, urlunparse


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
    """
    return to_sync_url(to_session_mode_url(url))
