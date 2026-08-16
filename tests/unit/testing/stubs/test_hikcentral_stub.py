from __future__ import annotations

import socket

import httpx
import pytest

from tr_shared.exceptions import ServiceUnavailableError
from tr_shared.integrations.hikcentral import hikcentral_get_version, hikcentral_probe_attendance
from tr_shared.testing.stubs.hikcentral import HikCentralStub

_REAL_GETADDRINFO = socket.getaddrinfo


@pytest.fixture(autouse=True)
def _stub_dns_for_hik_test_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """hikcentral_get_version/hikcentral_probe_attendance resolve `base_url`'s
    host before calling out (SSRF guard) — `hik.test` (RFC 2606) never
    resolves in real DNS, so fake it to a safe public IP here."""

    def _stub(host: str, *args: object, **kwargs: object) -> list:
        if host == "hik.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 0))]
        return _REAL_GETADDRINFO(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "getaddrinfo", _stub)


@pytest.mark.asyncio
async def test_version_and_attendance_routes() -> None:
    stub = HikCentralStub().version().attendance()

    async with httpx.AsyncClient(transport=stub.build(), base_url="https://hik.test") as client:
        version_resp = await client.get("/api/common/v1/version")
        attendance_resp = await client.post("/api/attendance/v1/report", json={})

    assert version_resp.json()["code"] == "0"
    assert attendance_resp.json()["code"] == "0"
    assert len(stub.requests) == 2


@pytest.mark.asyncio
async def test_stub_satisfies_the_real_get_version_function() -> None:
    """The stub isn't just self-consistent — it must actually satisfy the real
    production function that calls it, not a hand-rolled assertion of its own
    shape."""
    stub = HikCentralStub().version()

    async with httpx.AsyncClient(transport=stub.build()) as client:
        result = await hikcentral_get_version(client, "https://hik.test", "app-key", "secret")

    assert result["code"] == "0"


@pytest.mark.asyncio
async def test_stub_satisfies_the_real_probe_attendance_function() -> None:
    stub = HikCentralStub().attendance()

    async with httpx.AsyncClient(transport=stub.build()) as client:
        result = await hikcentral_probe_attendance(client, "https://hik.test", "app-key", "secret")

    assert result["code"] == "0"


@pytest.mark.asyncio
async def test_version_failure_mode_raises_through_real_function() -> None:
    stub = HikCentralStub().version(success=False, msg="Invalid signature")

    async with httpx.AsyncClient(transport=stub.build()) as client:
        with pytest.raises(ServiceUnavailableError) as exc:
            await hikcentral_get_version(client, "https://hik.test", "app-key", "secret")

    assert "Invalid signature" in exc.value.detail_message


@pytest.mark.asyncio
async def test_attendance_failure_mode_raises_through_real_function() -> None:
    stub = HikCentralStub().attendance(success=False, msg="Module not licensed")

    async with httpx.AsyncClient(transport=stub.build()) as client:
        with pytest.raises(ServiceUnavailableError) as exc:
            await hikcentral_probe_attendance(client, "https://hik.test", "app-key", "secret")

    assert "Module not licensed" in exc.value.detail_message


def test_escape_hatch_route_passes_through() -> None:
    stub = HikCentralStub().route("GET", r"/custom$", json={"ok": True})
    assert stub.build() is not None
