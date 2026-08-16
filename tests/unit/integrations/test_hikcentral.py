"""Tests for HikCentral signing + connect-time validation probes.

Signature math must match tr-people-finance's HikCentralAPI._generate_signature
bit-for-bit — this module is the single source of truth both services share.
"""

import base64
import hashlib
import hmac
import ipaddress
import socket

import httpx
import pytest

from tr_shared.exceptions import ServiceUnavailableError
from tr_shared.integrations.hikcentral import (
    _assert_safe_hikcentral_host,
    hikcentral_get_version,
    hikcentral_probe_attendance,
    sign_hikcentral_request,
)

_REAL_GETADDRINFO = socket.getaddrinfo


@pytest.fixture(autouse=True)
def _stub_dns_for_placeholder_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every existing test in this file uses `hik.example`, a hostname that
    is guaranteed by RFC 2606 to never resolve — the SSRF guard added to
    hikcentral_get_version/hikcentral_probe_attendance now does a real
    `socket.getaddrinfo` before every call, which would fail all of them.
    Resolve any non-literal-IP hostname to a fixed safe public IP; literal
    IPs (used by TestAssertSafeHikcentralHost below to test the guard
    itself) pass through to the real resolver, which handles them without
    any network I/O."""

    def _stub(host: str, *args: object, **kwargs: object) -> list:
        if host.endswith(".invalid"):
            # RFC 2606: guaranteed to never resolve — let the real resolver
            # fail it, for the dedicated unresolvable-hostname test.
            return _REAL_GETADDRINFO(host, *args, **kwargs)  # type: ignore[arg-type]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 0))]
        return _REAL_GETADDRINFO(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "getaddrinfo", _stub)


def _make_client(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport)


def _reference_signature(method: str, path: str, secret_key: str) -> str:
    """Independent re-implementation of the sign-string math (not calling the
    function under test) — a real HMAC vector, not a tautology."""
    text_to_sign = f"{method.upper()}\napplication/json\napplication/json\n{path}"
    return base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), text_to_sign.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")


class TestSignHikcentralRequest:
    def test_matches_independently_computed_hmac_vector(self) -> None:
        headers = sign_hikcentral_request("GET", "/api/common/v1/version", "s3cr3t", "app-key-1")
        expected = _reference_signature("GET", "/artemis/api/common/v1/version", "s3cr3t")
        assert headers["X-Ca-Signature"] == expected

    def test_sets_app_key_verbatim(self) -> None:
        headers = sign_hikcentral_request("GET", "/api/common/v1/version", "secret", "my-app-key")
        assert headers["X-Ca-Key"] == "my-app-key"

    def test_timestamp_is_milliseconds_string(self) -> None:
        headers = sign_hikcentral_request("GET", "/api/common/v1/version", "secret", "key")
        assert headers["X-Ca-Timestamp"].isdigit()
        assert len(headers["X-Ca-Timestamp"]) == 13  # ms epoch, not seconds

    def test_prepends_artemis_prefix_when_missing(self) -> None:
        with_prefix = sign_hikcentral_request("GET", "/artemis/api/x", "secret", "key")
        without_prefix = sign_hikcentral_request("GET", "/api/x", "secret", "key")
        # Both normalize to the same signed path -> same signature (modulo timestamp).
        assert with_prefix["X-Ca-Key"] == without_prefix["X-Ca-Key"]

    def test_prepends_leading_slash_when_missing(self) -> None:
        headers = sign_hikcentral_request("GET", "api/common/v1/version", "secret", "key")
        expected = _reference_signature("GET", "/artemis/api/common/v1/version", "secret")
        assert headers["X-Ca-Signature"] == expected

    def test_different_methods_produce_different_signatures(self) -> None:
        get_headers = sign_hikcentral_request("GET", "/api/x", "secret", "key")
        post_headers = sign_hikcentral_request("POST", "/api/x", "secret", "key")
        assert get_headers["X-Ca-Signature"] != post_headers["X-Ca-Signature"]


class TestHikcentralGetVersion:
    @pytest.mark.asyncio
    async def test_real_device_response_shape_parses_as_success(self) -> None:
        """Confirmed against a real HikCentral device probe this session:
        {"code": "0", "msg": "Success", "data": ""} — empty-string data is fine."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "0", "msg": "Success", "data": ""})

        async with _make_client(httpx.MockTransport(handler)) as client:
            result = await hikcentral_get_version(client, "https://hik.example", "key", "secret")
        assert result["code"] == "0"

    @pytest.mark.asyncio
    async def test_trailing_slash_base_url_is_normalized(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"code": "0", "msg": "Success", "data": ""})

        async with _make_client(httpx.MockTransport(handler)) as client:
            await hikcentral_get_version(client, "https://hik.example/", "key", "secret")
        assert captured["url"] == "https://hik.example/api/common/v1/version"
        assert "//api" not in captured["url"]

    @pytest.mark.asyncio
    async def test_hikcentral_reported_failure_code_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "1", "msg": "Invalid signature"})

        async with _make_client(httpx.MockTransport(handler)) as client:
            with pytest.raises(ServiceUnavailableError) as exc:
                await hikcentral_get_version(client, "https://hik.example", "key", "secret")
        assert "Invalid signature" in exc.value.detail_message

    @pytest.mark.asyncio
    async def test_non_200_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        async with _make_client(httpx.MockTransport(handler)) as client:
            with pytest.raises(ServiceUnavailableError):
                await hikcentral_get_version(client, "https://hik.example", "key", "secret")

    @pytest.mark.asyncio
    async def test_network_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        async with _make_client(httpx.MockTransport(handler)) as client:
            with pytest.raises(ServiceUnavailableError):
                await hikcentral_get_version(client, "https://hik.example", "key", "secret")

    @pytest.mark.asyncio
    async def test_non_json_response_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        async with _make_client(httpx.MockTransport(handler)) as client:
            with pytest.raises(ServiceUnavailableError):
                await hikcentral_get_version(client, "https://hik.example", "key", "secret")


class TestHikcentralProbeAttendance:
    @pytest.mark.asyncio
    async def test_success_returns_result(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "0", "msg": "Success", "data": {}})

        async with _make_client(httpx.MockTransport(handler)) as client:
            result = await hikcentral_probe_attendance(
                client, "https://hik.example", "key", "secret"
            )
        assert result["code"] == "0"

    @pytest.mark.asyncio
    async def test_page_size_one_and_one_day_window(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            captured["body"] = _json.loads(request.content)
            return httpx.Response(200, json={"code": "0", "msg": "Success", "data": {}})

        async with _make_client(httpx.MockTransport(handler)) as client:
            await hikcentral_probe_attendance(client, "https://hik.example", "key", "secret")

        req = captured["body"]["attendanceReportRequest"]
        assert req["pageSize"] == 1
        assert req["queryInfo"]["endTime"] - req["queryInfo"]["beginTime"] == 24 * 60 * 60 * 1000

    @pytest.mark.asyncio
    async def test_unlicensed_module_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "1", "msg": "Module not licensed"})

        async with _make_client(httpx.MockTransport(handler)) as client:
            with pytest.raises(ServiceUnavailableError) as exc:
                await hikcentral_probe_attendance(client, "https://hik.example", "key", "secret")
        assert "Module not licensed" in exc.value.detail_message

    @pytest.mark.asyncio
    async def test_trailing_slash_base_url_is_normalized(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"code": "0", "msg": "Success", "data": {}})

        async with _make_client(httpx.MockTransport(handler)) as client:
            await hikcentral_probe_attendance(client, "https://hik.example/", "key", "secret")
        assert captured["url"] == "https://hik.example/api/attendance/v1/report"
        assert "//api" not in captured["url"]


class TestAssertSafeHikcentralHost:
    """SSRF guard: block addresses that are never a real HikCentral device,
    allow the private-LAN ranges the feature actually targets."""

    def test_loopback_rejected(self) -> None:
        with pytest.raises(ServiceUnavailableError):
            _assert_safe_hikcentral_host("https://127.0.0.1:8443")

    def test_ipv6_loopback_rejected(self) -> None:
        with pytest.raises(ServiceUnavailableError):
            _assert_safe_hikcentral_host("https://[::1]:8443")

    def test_link_local_cloud_metadata_rejected(self) -> None:
        with pytest.raises(ServiceUnavailableError):
            _assert_safe_hikcentral_host("http://169.254.169.254")

    def test_multicast_rejected(self) -> None:
        with pytest.raises(ServiceUnavailableError):
            _assert_safe_hikcentral_host("http://224.0.0.1")

    def test_non_http_scheme_rejected(self) -> None:
        with pytest.raises(ServiceUnavailableError):
            _assert_safe_hikcentral_host("ftp://192.168.1.100")

    def test_missing_hostname_rejected(self) -> None:
        with pytest.raises(ServiceUnavailableError):
            _assert_safe_hikcentral_host("https:///no-host")

    def test_unresolvable_hostname_rejected(self) -> None:
        with pytest.raises(ServiceUnavailableError):
            _assert_safe_hikcentral_host("https://this-host-does-not-exist.invalid")

    def test_private_lan_address_allowed(self) -> None:
        """The actual, intended use case — a real HikCentral box on a
        tenant's on-prem LAN. Must NOT be blocked."""
        _assert_safe_hikcentral_host("https://192.168.1.100:8443")

    def test_public_address_allowed(self) -> None:
        _assert_safe_hikcentral_host("https://203.0.113.10")

    @pytest.mark.asyncio
    async def test_get_version_rejects_loopback_before_any_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("request must never be sent for a loopback base_url")

        async with _make_client(httpx.MockTransport(handler)) as client:
            with pytest.raises(ServiceUnavailableError):
                await hikcentral_get_version(client, "http://127.0.0.1", "key", "secret")

    @pytest.mark.asyncio
    async def test_probe_attendance_rejects_link_local_before_any_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("request must never be sent for a link-local base_url")

        async with _make_client(httpx.MockTransport(handler)) as client:
            with pytest.raises(ServiceUnavailableError):
                await hikcentral_probe_attendance(client, "http://169.254.169.254", "key", "secret")
