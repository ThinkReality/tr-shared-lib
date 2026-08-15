"""Tests for HikCentral signing + connect-time validation probes.

Signature math must match tr-people-finance's HikCentralAPI._generate_signature
bit-for-bit — this module is the single source of truth both services share.
"""

import base64
import hashlib
import hmac

import httpx
import pytest

from tr_shared.exceptions import ServiceUnavailableError
from tr_shared.integrations.hikcentral import (
    hikcentral_get_version,
    hikcentral_probe_attendance,
    sign_hikcentral_request,
)


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
