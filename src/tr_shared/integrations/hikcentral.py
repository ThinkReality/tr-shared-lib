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
import time
from typing import Any

import httpx

from tr_shared.exceptions import ServiceUnavailableError

__all__ = [
    "sign_hikcentral_request",
    "hikcentral_get_version",
    "hikcentral_probe_attendance",
]


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
        ServiceUnavailableError: on network failure or non-2xx response.
    """
    normalized_base = base_url.rstrip("/")
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
        ServiceUnavailableError: on network failure, non-2xx, or a
            HikCentral-reported failure code.
    """
    normalized_base = base_url.rstrip("/")
    path = "/api/attendance/v1/report"
    url = f"{normalized_base}{path}"
    headers = sign_hikcentral_request("POST", path, secret_key, app_key)
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"

    now_ms = int(time.time() * 1000)
    one_day_ms = 24 * 60 * 60 * 1000
    payload = {
        "attendanceReportRequest": {
            "pageNo": 1,
            "pageSize": 1,
            "queryInfo": {
                "beginTime": now_ms - one_day_ms,
                "endTime": now_ms,
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
