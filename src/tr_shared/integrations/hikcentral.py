"""HikCentral Artemis OpenAPI signing + connect-time validation probes.

HikCentral (on-prem biometric attendance/access-control portal) uses a
self-contained HMAC-SHA256 auth scheme — no OAuth, no token exchange:

  sign_string = f"{METHOD}\\napplication/json\\napplication/json\\n/artemis{path}"
  signature   = base64(hmac_sha256(secret_key, sign_string))
  headers     = {X-Ca-Key: app_key, X-Ca-Signature: signature, X-Ca-Timestamp: ts_ms}

Ported verbatim from tr-people-finance's HikCentralAPI._generate_signature —
this module is the single source of truth for that signing math, shared
between tr-crm-core (connect-flow validation, one-shot) and tr-people-finance
(HR domain client, which keeps its own retry/backoff/lifecycle and calls into
this module instead of maintaining its own copy).

Deliberately function-based, not a class: these are one-shot, caller-owns-the-
client probes with no cache or connection state to hold between calls — see
plans/2026-08-15-hikcentral-per-tenant-integration.md, Key design decision 1.
"""

import base64
import hashlib
import hmac
import ipaddress
import socket
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from tr_shared.exceptions import ServiceUnavailableError

__all__ = [
    "sign_hikcentral_request",
    "hikcentral_get_version",
    "hikcentral_probe_attendance",
]


def _assert_safe_hikcentral_host(base_url: str) -> None:
    """Reject a `base_url` that resolves somewhere it can never legitimately be.

    HikCentral devices are on-prem LAN hardware — the whole point of this
    integration is connecting to a tenant's private-range IP (the plan's own
    connect-form placeholder is `192.168.1.100`), so RFC1918/ULA ranges are
    NOT blocked here; that would break the feature. What IS blocked is the
    address classes that are NEVER a real HikCentral box: loopback (the
    server probing itself), link-local (169.254.0.0/16 — cloud metadata
    endpoints, the #1 SSRF target), multicast, and reserved/unspecified.

    Resolves the hostname and checks the resolved IP(s), not the string —
    a bare `host in {"localhost", ...}` denylist is trivially bypassed by an
    alternate IP encoding or a DNS record pointed at 127.0.0.1. Every
    resolved address must be safe, or the whole `base_url` is rejected.

    Known limitation: this check and the actual connection are two separate
    DNS resolutions (`httpx` resolves again internally), so a short-TTL
    record could rebind between them (TOCTOU). Accepted for this integration
    given the caller is a per-tenant admin, not an anonymous request — not a
    complete SSRF fix for an untrusted-caller boundary.

    Raises:
        ServiceUnavailableError: scheme is not http/https, hostname is
            missing/unresolvable, or any resolved address is unsafe.
    """
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ServiceUnavailableError(
            detail=f"HikCentral base_url must use http(s), got scheme {parsed.scheme!r}",
            code="HIKCENTRAL_UNSAFE_URL_001",
        )
    hostname = parsed.hostname
    if not hostname:
        raise ServiceUnavailableError(
            detail="HikCentral base_url has no hostname",
            code="HIKCENTRAL_UNSAFE_URL_001",
        )

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ServiceUnavailableError(
            detail=f"HikCentral base_url host {hostname!r} could not be resolved: {exc}",
            code="HIKCENTRAL_UNSAFE_URL_002",
        ) from exc

    for family, _, _, _, sockaddr in addr_infos:
        raw_ip = sockaddr[0]
        ip = ipaddress.ip_address(raw_ip)
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ServiceUnavailableError(
                detail=f"HikCentral base_url host {hostname!r} resolves to a disallowed address ({raw_ip})",
                code="HIKCENTRAL_UNSAFE_URL_003",
            )


def sign_hikcentral_request(
    method: str, path: str, secret_key: str, app_key: str
) -> dict[str, str]:
    """Compute HikCentral Artemis auth headers for one request.

    Pure function, no I/O. `path` is normalized to always start with
    `/artemis` before signing, matching the live device's expected sign string.

    Returns:
        {"X-Ca-Key", "X-Ca-Signature", "X-Ca-Timestamp"} — merge into request headers.
    """
    url_path = path if path.startswith("/") else f"/{path}"
    if not url_path.startswith("/artemis"):
        url_path = f"/artemis{url_path}"

    sign_string = f"{method.upper()}\napplication/json\napplication/json\n{url_path}"

    signature = base64.b64encode(
        hmac.new(
            key=secret_key.encode("utf-8"),
            msg=sign_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    timestamp = str(int(time.time() * 1000))

    return {
        "X-Ca-Key": app_key,
        "X-Ca-Signature": signature,
        "X-Ca-Timestamp": timestamp,
    }


async def hikcentral_get_version(
    client: httpx.AsyncClient,
    base_url: str,
    app_key: str,
    secret_key: str,
) -> dict[str, Any]:
    """One-shot GET /api/common/v1/version — proves signing/auth is correct.

    Caller owns `client`'s full lifecycle, including `verify=` at construction
    time — no `verify_ssl` param here, it would be dead weight since the
    client already carries it. `base_url` is `.rstrip("/")`-normalized here because
    a Pydantic `HttpUrl` appends a trailing slash on `str()`, which would
    otherwise double-slash both the request URL and the signed path — silently
    breaking the signature (looks like wrong credentials, not a URL bug).

    Raises:
        ServiceUnavailableError: `base_url` resolves to a disallowed
            address (see `_assert_safe_hikcentral_host`), on network
            failure, or on a non-2xx response.
    """
    normalized_base = base_url.rstrip("/")
    _assert_safe_hikcentral_host(normalized_base)
    path = "/api/common/v1/version"
    url = f"{normalized_base}{path}"
    headers = sign_hikcentral_request("GET", path, secret_key, app_key)
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"

    try:
        response = await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        raise ServiceUnavailableError(
            detail=f"HikCentral unreachable: {exc}",
            code="HIKCENTRAL_UNAVAILABLE_001",
        ) from exc

    if response.status_code != 200:
        raise ServiceUnavailableError(
            detail=f"HikCentral version probe returned HTTP {response.status_code}",
            code="HIKCENTRAL_UPSTREAM_001",
        )

    try:
        result: dict[str, Any] = response.json()
    except ValueError as exc:
        raise ServiceUnavailableError(
            detail="Invalid JSON response from HikCentral version probe",
            code="HIKCENTRAL_RESPONSE_001",
        ) from exc

    if result.get("code") != "0":
        raise ServiceUnavailableError(
            detail=f"HikCentral version check failed: {result.get('msg', 'Unknown error')}",
            code="HIKCENTRAL_AUTH_001",
        )

    return result


async def hikcentral_probe_attendance(
    client: httpx.AsyncClient,
    base_url: str,
    app_key: str,
    secret_key: str,
) -> dict[str, Any]:
    """One-shot POST /api/attendance/v1/report, page_size=1 — proves the
    attendance module is licensed/reachable, not just that credentials sign
    correctly. Capability probe only; does not paginate or aggregate.

    Raises:
        ServiceUnavailableError: `base_url` resolves to a disallowed
            address (see `_assert_safe_hikcentral_host`), on network
            failure, non-2xx, or a HikCentral-reported failure code.
    """
    normalized_base = base_url.rstrip("/")
    _assert_safe_hikcentral_host(normalized_base)
    path = "/api/attendance/v1/report"
    url = f"{normalized_base}{path}"
    headers = sign_hikcentral_request("POST", path, secret_key, app_key)
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"

    # beginTime/endTime are device-validated strings, not epoch milliseconds —
    # sending an int here reads as a well-formed request but the device
    # rejects it with "Incorrect request parameter. [beginTime parameter
    # error]". Format mirrors tr-people-finance's hikcentral_query_window()
    # default path (app/modules/hr/services/attendance/calculations.py),
    # the proven-working production caller of this same endpoint — including
    # its literal " 04:00" suffix (space, no '+').
    today = date.today()
    yesterday = today - timedelta(days=1)
    payload = {
        "attendanceReportRequest": {
            "pageNo": 1,
            "pageSize": 1,
            "queryInfo": {
                "beginTime": f"{yesterday.isoformat()}T00:00:00 04:00",
                "endTime": f"{today.isoformat()}T23:59:59 04:00",
                "sortInfo": {"sortField": 1, "sortType": 1},
                "personID": [],
            },
        }
    }

    try:
        response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise ServiceUnavailableError(
            detail=f"HikCentral unreachable: {exc}",
            code="HIKCENTRAL_UNAVAILABLE_001",
        ) from exc

    if response.status_code != 200:
        raise ServiceUnavailableError(
            detail=f"HikCentral attendance probe returned HTTP {response.status_code}",
            code="HIKCENTRAL_UPSTREAM_001",
        )

    try:
        result: dict[str, Any] = response.json()
    except ValueError as exc:
        raise ServiceUnavailableError(
            detail="Invalid JSON response from HikCentral attendance probe",
            code="HIKCENTRAL_RESPONSE_001",
        ) from exc

    if result.get("code") != "0":
        raise ServiceUnavailableError(
            detail=(
                "HikCentral attendance module unreachable/unlicensed: "
                f"{result.get('msg', 'Unknown error')}"
            ),
            code="HIKCENTRAL_LICENSE_001",
        )

    return result
