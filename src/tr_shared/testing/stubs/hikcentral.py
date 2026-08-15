"""HikCentral test fake — one `httpx.MockTransport`-backed stub for the two
connect-time validation endpoints tr-crm-core's `HikCentralRegistrar` and
tr-people-finance's `HikCentralAPI` both call through the shared
`tr_shared.integrations.hikcentral` signing functions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tr_shared.testing.stubs.http_stub import MockTransportBuilder

if TYPE_CHECKING:
    import httpx

__all__ = ["HikCentralStub"]


class HikCentralStub:
    """
    stub = HikCentralStub()
    stub.version()
    stub.attendance()
    client = httpx.AsyncClient(transport=stub.build(), base_url="https://hik.example")
    """

    def __init__(self) -> None:
        self._builder = MockTransportBuilder()

    def version(self, *, success: bool = True, msg: str = "Success") -> "HikCentralStub":
        """GET /api/common/v1/version — the auth probe."""
        body: dict[str, Any] = (
            {"code": "0", "msg": msg, "data": ""}
            if success
            else {"code": "1", "msg": msg}
        )
        self._builder.route("GET", r"/api/common/v1/version$", json=body)
        return self

    def attendance(self, *, success: bool = True, msg: str = "Success") -> "HikCentralStub":
        """POST /api/attendance/v1/report — the capability/licensing probe."""
        body: dict[str, Any] = (
            {"code": "0", "msg": msg, "data": {}} if success else {"code": "1", "msg": msg}
        )
        self._builder.route("POST", r"/api/attendance/v1/report$", json=body)
        return self

    def route(self, *args: Any, **kwargs: Any) -> "HikCentralStub":
        """Escape hatch for endpoints this stub doesn't wrap yet — same
        MockTransportBuilder.route() signature (persons/events/ACS devices
        stay HR-only, not part of the connect-validation surface this stub
        covers, so they aren't pre-wired here)."""
        self._builder.route(*args, **kwargs)
        return self

    @property
    def requests(self) -> list[Any]:
        return self._builder.requests

    def build(self) -> "httpx.MockTransport":
        return self._builder.build()
