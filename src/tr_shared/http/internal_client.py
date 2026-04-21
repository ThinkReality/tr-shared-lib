"""Typed wrapper around ``ServiceHTTPClient`` for ``/api/v1/internal/*`` endpoints.

Adds:
- Standard SuccessResponse envelope parsing (returns ``.data``).
- Auto ``X-Tenant-ID`` header injection.
- Typed error mapping: HTTP status + response body → ``tr_shared.exceptions.*``.

Subclass per target service::

    class LeadInternalClient(InternalServiceClient):
        BASE_PATH = "/api/v1/internal"

        async def get_source_performance(
            self, *, tenant_id: UUID, source_id: UUID | None = None,
        ) -> dict:
            params = {"source_id": str(source_id)} if source_id else None
            return await self._get(
                "/leads/source-performance",
                params=params,
                tenant_id=tenant_id,
            )
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from tr_shared.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BaseAPIException,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)
from tr_shared.http.client import ServiceHTTPClient


def _envelope_data(envelope: Any) -> Any:
    """Extract ``.data`` from a SuccessResponse envelope.

    Raises ``ServiceUnavailableError`` if the response is not a dict or
    lacks a ``data`` key — cleaner than silently returning garbage.
    """
    if not isinstance(envelope, dict):
        raise ServiceUnavailableError(
            detail="Internal response was not a JSON object",
            code="INTERNAL_CLIENT_ENVELOPE_001",
        )
    if "data" not in envelope:
        raise ServiceUnavailableError(
            detail="Internal response missing 'data' field",
            code="INTERNAL_CLIENT_ENVELOPE_002",
        )
    return envelope["data"]


def _translate_status_error(exc: httpx.HTTPStatusError) -> BaseAPIException:
    """Translate a FastAPI error envelope (4xx/5xx) into a tr_shared exception."""
    status = exc.response.status_code
    body: dict[str, Any] = {}
    try:
        body = exc.response.json()
    except Exception:  # noqa: BLE001 — non-JSON error payloads end up 500-ish
        body = {}

    detail = body.get("detail") or body.get("error") or exc.response.text or "Internal error"
    code = body.get("code") or "INTERNAL_CLIENT_001"

    if status == 400:
        return ValidationError(detail=detail, code=code)
    if status == 401:
        return AuthenticationError(detail=detail, code=code)
    if status == 403:
        return AuthorizationError(detail=detail, code=code)
    if status == 404:
        return NotFoundError(
            resource=body.get("error", "Resource"),
            identifier=None,
            code=code,
        )
    if status == 409:
        return ConflictError(detail=detail, code=code)
    if status == 429:
        return RateLimitError(detail=detail, code=code)
    # 5xx / unexpected status
    return ServiceUnavailableError(detail=detail, code=code)


class InternalServiceClient:
    """Base class for service-to-service internal API clients.

    Args:
        http: The underlying ``ServiceHTTPClient`` (owned by the caller —
            manage ``close()`` / lifespan at app level).
    """

    BASE_PATH: str = ""

    def __init__(self, http: ServiceHTTPClient) -> None:
        self._http = http

    # ── Public verb helpers ──────────────────────────────────────────

    async def _get(
        self,
        path: str,
        *,
        tenant_id: UUID | str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._call("GET", path, tenant_id=tenant_id, params=params)

    async def _post(
        self,
        path: str,
        *,
        tenant_id: UUID | str | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        return await self._call("POST", path, tenant_id=tenant_id, json=json)

    async def _patch(
        self,
        path: str,
        *,
        tenant_id: UUID | str | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        return await self._call("PATCH", path, tenant_id=tenant_id, json=json)

    async def _delete(
        self,
        path: str,
        *,
        tenant_id: UUID | str | None = None,
    ) -> Any:
        return await self._call("DELETE", path, tenant_id=tenant_id)

    # ── Core request pipeline ────────────────────────────────────────

    async def _call(
        self,
        method: str,
        path: str,
        *,
        tenant_id: UUID | str | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        full_path = f"{self.BASE_PATH}{path}" if self.BASE_PATH else path
        headers: dict[str, str] = {}
        if tenant_id is not None:
            headers["X-Tenant-ID"] = str(tenant_id)

        try:
            if method == "GET":
                envelope = await self._http.get(full_path, params=params, headers=headers)
            elif method == "POST":
                envelope = await self._http.post(full_path, json=json, headers=headers)
            elif method == "PATCH":
                envelope = await self._http.patch(full_path, json=json, headers=headers)
            elif method == "DELETE":
                envelope = await self._http.delete(full_path, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")

        except httpx.HTTPStatusError as exc:
            raise _translate_status_error(exc) from exc
        except httpx.TimeoutException as exc:
            raise ServiceTimeoutError(
                detail=f"Timeout calling {full_path}",
                code="INTERNAL_CLIENT_TIMEOUT_001",
            ) from exc
        except ConnectionError as exc:
            # ServiceHTTPClient raises ConnectionError when the breaker is
            # open or retries are exhausted.
            raise ServiceUnavailableError(
                detail=str(exc),
                code="INTERNAL_CLIENT_UNAVAILABLE_001",
            ) from exc
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError(
                detail=f"HTTP error calling {full_path}: {exc.__class__.__name__}",
                code="INTERNAL_CLIENT_HTTP_001",
            ) from exc

        # DELETE endpoints commonly return 204 → empty dict envelope. Return
        # None explicitly so callers don't try to unpack a missing ``data``.
        if envelope == {}:
            return None
        return _envelope_data(envelope)


__all__ = ["InternalServiceClient"]
