"""Unit tests for the Supabase Vault write path (``tr_shared.vault.VaultService``).

Lane note: there is no integration lane for this. ``vault.*`` is a Supabase
extension and is absent from the ``postgres:16-alpine`` container the test
plugin provisions, and TR_Testing_Standard forbids a test reaching remote
Supabase. So the session is a recording fake — same precedent as
``tests/test_repository_tenant_guard.py``'s ``_FakeSession`` — and the
assertions pin the emitted SQL, its ordering, and the error mapping.
"""

import asyncio
from uuid import UUID, uuid4

import pytest

from tr_shared.exceptions import DatabaseError, ServiceUnavailableError
from tr_shared.vault import VaultService


class _FakeResult:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        return self._row


class _RecordingSession:
    """Records every ``(sql, params)`` pair in call order and replays rows."""

    def __init__(self, rows: list[tuple | None] | None = None, delay: float = 0.0) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._rows = list(rows or [])
        self._delay = delay

    async def execute(self, statement, params=None):
        if self._delay:
            await asyncio.sleep(self._delay)
        self.calls.append((str(statement), params or {}))
        row = self._rows.pop(0) if self._rows else None
        return _FakeResult(row)


def _sql(session: _RecordingSession, index: int) -> str:
    return " ".join(session.calls[index][0].split())


async def test_create_secret_deletes_by_name_before_inserting():
    """The collision guard must run BEFORE the insert.

    ``vault.secrets.name`` carries a real non-partial unique constraint, so a
    stale row from a partial write would otherwise raise an unhandled
    IntegrityError forever. Inverting the two statements would delete the row
    that was just created — silent token loss — so the order is asserted, not
    just the membership.
    """
    secret_id = uuid4()
    session = _RecordingSession(rows=[None, (secret_id,)])

    returned = await VaultService(session).create_secret(
        "refresh-token", name="calendar:conn:abc", description="google calendar"
    )

    assert returned == secret_id
    assert len(session.calls) == 2
    assert _sql(session, 0) == "DELETE FROM vault.secrets WHERE name = :name"
    assert session.calls[0][1] == {"name": "calendar:conn:abc"}
    assert "vault.create_secret(:secret, :name, :description)" in _sql(session, 1)
    assert session.calls[1][1] == {
        "secret": "refresh-token",
        "name": "calendar:conn:abc",
        "description": "google calendar",
    }


async def test_create_secret_without_name_emits_no_delete():
    session = _RecordingSession(rows=[(uuid4(),)])

    await VaultService(session).create_secret("refresh-token")

    assert len(session.calls) == 1
    assert "DELETE" not in _sql(session, 0)
    assert session.calls[0][1] == {"secret": "refresh-token", "name": None, "description": ""}


@pytest.mark.parametrize("row", [None, (None,)])
async def test_create_secret_without_returned_id_raises_database_error(row):
    session = _RecordingSession(rows=[row])

    with pytest.raises(DatabaseError) as exc:
        await VaultService(session).create_secret("refresh-token")

    assert exc.value.error_code == "DATABASE_001"


async def test_read_secret_returns_plaintext():
    secret_id = uuid4()
    session = _RecordingSession(rows=[("plaintext-token",)])

    assert await VaultService(session).read_secret(secret_id) == "plaintext-token"
    assert _sql(session, 0) == (
        "SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = :secret_id"
    )
    assert session.calls[0][1] == {"secret_id": str(secret_id)}


async def test_read_secret_missing_returns_none_and_does_not_raise():
    """A secret that is not there is not a database failure."""
    session = _RecordingSession(rows=[None])

    assert await VaultService(session).read_secret(uuid4()) is None


async def test_update_secret_calls_vault_update():
    secret_id = uuid4()
    session = _RecordingSession()

    await VaultService(session).update_secret(secret_id, "new-token", name="calendar:conn:abc")

    assert "vault.update_secret(:secret_id, :secret, :name, :description)" in _sql(session, 0)
    assert session.calls[0][1] == {
        "secret_id": str(secret_id),
        "secret": "new-token",
        "name": "calendar:conn:abc",
        "description": None,
    }


async def test_delete_secret_deletes_by_id():
    secret_id = uuid4()
    session = _RecordingSession()

    await VaultService(session).delete_secret(secret_id)

    assert _sql(session, 0) == "DELETE FROM vault.secrets WHERE id = :secret_id"
    assert session.calls[0][1] == {"secret_id": str(secret_id)}


@pytest.mark.parametrize(
    "method,args",
    [
        ("create_secret", ("token",)),
        ("read_secret", (UUID(int=1),)),
        ("update_secret", (UUID(int=1), "token")),
        ("delete_secret", (UUID(int=1),)),
    ],
)
async def test_timeout_raises_service_unavailable_with_generic_code(method, args):
    """The timeout is a constructor parameter — a shared lib cannot read a
    service's ``VAULT_TIMEOUT_SECONDS``. The code stays generic to ``tr_shared``;
    it is never ``ADMIN_VAULT_002``.
    """
    session = _RecordingSession(rows=[(uuid4(),)], delay=0.5)
    service = VaultService(session, timeout_seconds=0.01)

    with pytest.raises(ServiceUnavailableError) as exc:
        await getattr(service, method)(*args)

    assert exc.value.error_code == "SERVICE_UNAVAILABLE_001"
