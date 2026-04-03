"""
Global error handler middleware with Slack alerts.

Merged from crm-backend (rich Slack blocks, rate limiting, 5xx detection)
and tr-lead-management (privacy hashing, auth-context extraction).

Usage::

    from tr_shared.middleware import GlobalErrorHandlerMiddleware

    app.add_middleware(
        GlobalErrorHandlerMiddleware,
        service_name="tr-listing-service",
        environment="production",
        slack_webhook_url=settings.SLACK_ERROR_WEBHOOK_URL,
    )
"""

import asyncio
import hashlib
import logging
import os
import socket
import traceback
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Module-level shared httpx client for Slack webhook calls
_slack_client: httpx.AsyncClient | None = None


def _get_slack_client() -> httpx.AsyncClient:
    global _slack_client
    if _slack_client is None or _slack_client.is_closed:
        _slack_client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(max_keepalive_connections=2, max_connections=5),
        )
    return _slack_client


async def close_slack_client() -> None:
    """Call on app shutdown to release Slack HTTP resources."""
    global _slack_client
    if _slack_client and not _slack_client.is_closed:
        await _slack_client.aclose()
        _slack_client = None


def _hash_identifier(value: str) -> str:
    """SHA-256 hash (first 16 chars) for privacy-preserving alerts."""
    if not value:
        return "N/A"
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


_pending_alerts: set[asyncio.Task] = set()


class GlobalErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Catches all unhandled exceptions and 5xx responses.

    - Logs structured error context
    - Sends rate-limited Slack alerts (5 per error type per hour)
    - Returns standardised error JSON

    Args:
        app: ASGI application.
        service_name: For Slack alert titles.
        environment: "development", "staging", "production".
        slack_webhook_url: Slack incoming-webhook URL (empty = no alerts).
        alert_on_5xx: Also alert on handled 5xx responses (default True).
        hash_pii: SHA-256-hash user/tenant IDs in alerts (default True).
        rate_limit: Max alerts per error type per hour (default 5).
    """

    def __init__(
        self,
        app,
        service_name: str = "unknown",
        environment: str = "development",
        slack_webhook_url: str = "",
        alert_on_5xx: bool = True,
        hash_pii: bool = True,
        rate_limit: int = 5,
    ) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.environment = environment
        self.slack_webhook_url = slack_webhook_url
        self.alert_on_5xx = alert_on_5xx
        self.hash_pii = hash_pii
        self.rate_limit = rate_limit
        self._error_counts: dict[str, int] = defaultdict(int)
        self._error_timestamps: dict[str, datetime] = {}

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)

            if self.alert_on_5xx and response.status_code >= 500:
                # Buffer body to extract error detail for the alert
                body_bytes = b"".join([chunk async for chunk in response.body_iterator])
                body_text = body_bytes.decode("utf-8", errors="replace")[:500]

                ctx = self._build_context(
                    request,
                    status_code=response.status_code,
                    response_body=body_text,
                )
                logger.error("Handled 5xx response", extra=ctx)
                self._fire_alert(ctx)

                # Re-wrap so the client still receives the body.
                # Build headers from the raw ASGI scope list to avoid
                # KeyError in Starlette's MutableHeaders.__getitem__
                # when duplicate or encoded header keys are present.
                raw_headers = {
                    k.decode("latin-1"): v.decode("latin-1")
                    for k, v in response.raw_headers
                }
                return Response(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=raw_headers,
                )

            return response

        except Exception as exc:
            ctx = self._build_context(
                request,
                error=str(exc),
                error_type=type(exc).__name__,
                tb=traceback.format_exc(),
                status_code=500,
            )
            logger.error("Unhandled exception", extra=ctx, exc_info=True)
            self._fire_alert(ctx)

            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "message": "Internal server error",
                        "code": "INTERNAL_ERROR",
                        "correlation_id": ctx.get("correlation_id", "unknown"),
                    }
                },
            )

    # ── Helpers ──────────────────────────────────────────────────────

    def _build_context(
        self,
        request: Request,
        error: str = "",
        error_type: str = "",
        tb: str | None = None,
        status_code: int = 500,
        response_body: str = "",
    ) -> dict:
        user_id, tenant_id = self._extract_identity(request)
        if self.hash_pii:
            user_id = _hash_identifier(user_id) if user_id else None
            tenant_id = _hash_identifier(tenant_id) if tenant_id else None

        return {
            "service": self.service_name,
            "environment": self.environment,
            "path": request.url.path,
            "query": str(request.url.query) if request.url.query else "",
            "method": request.method,
            "status_code": status_code,
            "error": error or f"HTTP {status_code}",
            "error_type": error_type or f"HTTP{status_code}",
            "user_id": user_id,
            "tenant_id": tenant_id,
            "correlation_id": getattr(request.state, "correlation_id", "unknown"),
            "traceback": tb,
            "response_body": response_body,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "host": os.environ.get("HOSTNAME", socket.gethostname()),
        }

    @staticmethod
    def _extract_identity(request: Request) -> tuple[str | None, str | None]:
        """Extract user/tenant from auth_context or legacy request.state.user."""
        if hasattr(request.state, "auth_context") and request.state.auth_context:
            ctx = request.state.auth_context
            return str(getattr(ctx, "user_id", None)), str(
                getattr(ctx, "tenant_id", None)
            )
        user = getattr(request.state, "user", None)
        if user is None:
            return None, None
        if hasattr(user, "get"):
            return user.get("id"), user.get("tenant_id")
        return str(getattr(user, "id", None)), str(getattr(user, "tenant_id", None))

    def _fire_alert(self, ctx: dict) -> None:
        if not self.slack_webhook_url:
            return
        task = asyncio.create_task(self._send_slack_alert(ctx))
        _pending_alerts.add(task)
        task.add_done_callback(_pending_alerts.discard)

    async def _send_slack_alert(self, ctx: dict) -> None:
        error_key = f"{ctx['service']}:{ctx['error_type']}"
        now = datetime.now(UTC)

        if error_key not in self._error_timestamps:
            self._error_timestamps[error_key] = now
        if now - self._error_timestamps[error_key] > timedelta(hours=1):
            self._error_counts[error_key] = 0
            self._error_timestamps[error_key] = now
        if self._error_counts[error_key] >= self.rate_limit:
            return
        self._error_counts[error_key] += 1

        # Build path display with query string if present
        path_display = f"`{ctx['path']}`"
        if ctx.get("query"):
            path_display = f"`{ctx['path']}?{ctx['query']}`"

        # Build traceback / response body section
        tb = ctx.get("traceback")
        if tb:
            tb_text = f"*Traceback:*\n```{tb[-1500:]}```"
        else:
            body = ctx.get("response_body", "")
            tb_text = (
                f"_No exception raised (handled {ctx['status_code']} response)_\n"
                + (f"*Response body:*\n```{body}```" if body else "_No body available_")
            )

        message = {
            "text": f"{self.service_name} error ({self.environment})",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{self.service_name} — {ctx['error_type']}",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Env:*\n{self.environment}"},
                        {"type": "mrkdwn", "text": f"*Status:*\n{ctx['status_code']}"},
                        {"type": "mrkdwn", "text": f"*Method:*\n{ctx['method']}"},
                        {"type": "mrkdwn", "text": f"*Path:*\n{path_display}"},
                        {"type": "mrkdwn", "text": f"*User:*\n{ctx.get('user_id') or 'N/A'}"},
                        {"type": "mrkdwn", "text": f"*Tenant:*\n{ctx.get('tenant_id') or 'N/A'}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Error:*\n`{ctx['error'][:500]}`",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": tb_text,
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"{ctx.get('timestamp', '')} | "
                                f"host: {ctx.get('host', 'unknown')} | "
                                f"Correlation: `{ctx['correlation_id']}`"
                            ),
                        }
                    ],
                },
            ],
        }

        try:
            client = _get_slack_client()
            resp = await client.post(self.slack_webhook_url, json=message)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Failed to send Slack alert: %s", exc)
