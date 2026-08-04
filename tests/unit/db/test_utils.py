import pytest

from tr_shared.db import LIKE_ESCAPE_CHAR, escape_like, is_local_dsn


def test_escape_percent():
    assert escape_like("50%") == "50\\%"


def test_escape_underscore():
    assert escape_like("a_b") == "a\\_b"


def test_escape_backslash_first():
    # Backslash must be doubled BEFORE wildcards, else the wildcard escapes
    # would themselves be re-escaped.
    assert escape_like("a\\b") == "a\\\\b"


def test_escape_mixed():
    assert escape_like("\\%_") == "\\\\\\%\\_"


def test_escape_no_wildcards_unchanged():
    assert escape_like("plain text") == "plain text"


def test_escape_empty():
    assert escape_like("") == ""


def test_escape_char_constant():
    assert LIKE_ESCAPE_CHAR == "\\"


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://u:p@localhost:5432/db",
        "postgresql+asyncpg://u:p@127.0.0.1:5432/db",
        "postgresql+psycopg2://u:p@postgres:5432/db",
        "postgresql+asyncpg://u:p@postgres-test:5432/db",
        "postgresql+asyncpg://u:p@db:5432/db",
        "postgresql+asyncpg://u:p@tr-test-crm-core-abc123:5432/db",
        "postgresql+asyncpg://u:p@[::1]:5432/db",
    ],
)
def test_local_hosts_are_local(dsn):
    assert is_local_dsn(dsn) is True


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://u:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
        "postgresql+asyncpg://u:p@db.abcdefgh.supabase.co:5432/postgres",
        "postgresql+asyncpg://u:p@10.0.0.5:5432/db",
        "postgresql+asyncpg://u:p@dbserver.internal:5432/db",
    ],
)
def test_remote_hosts_are_not_local(dsn):
    assert is_local_dsn(dsn) is False


def test_host_matching_is_case_insensitive():
    assert is_local_dsn("postgresql+asyncpg://u:p@LOCALHOST:5432/db") is True


def test_a_prefixed_host_must_still_match_the_prefix_exactly():
    """`tr-test-` is a prefix rule, not a substring rule — a remote host that
    merely CONTAINS it is not local."""
    assert is_local_dsn("postgresql+asyncpg://u:p@evil.tr-test-x.com:5432/db") is False


@pytest.mark.parametrize("dsn", ["", "not-a-dsn", "postgresql+asyncpg:///db"])
def test_an_unparseable_dsn_is_not_local(dsn):
    """Unknown must never read as safe: both callers use this to decide whether
    a destructive action is permitted."""
    assert is_local_dsn(dsn) is False


def test_a_malformed_ipv6_host_is_not_local_rather_than_raising():
    """`urlsplit` raises ValueError on an unclosed IPv6 bracket (verified). A
    guard that dies on a malformed DSN is worse than one that calls it
    non-local, so the ValueError path is caught and answers False."""
    assert is_local_dsn("postgresql+asyncpg://u:p@[::1/db") is False


def test_an_unparseable_port_does_not_change_the_host_verdict():
    """Only `.port` raises on a non-numeric port, and this never reads `.port`.
    The host is still localhost, so the honest answer is local."""
    assert is_local_dsn("postgresql+asyncpg://u:p@localhost:notaport/db") is True
