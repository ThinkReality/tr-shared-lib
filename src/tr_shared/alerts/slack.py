"""The one Slack path in the lib: the per-key hourly budget and the Block Kit layout."""

import logging
import os
import socket
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

TASK_ALERTS_PER_HOUR = 5

_sync_client: httpx.Client | None = None


class SlackAlertBudget:
    def __init__(self, per_hour: int) -> None:
        self._per_hour = per_hour
        self._counts: dict[str, int] = defaultdict(int)
        self._window_started: dict[str, datetime] = {}

    def allow(self, key: str) -> bool:
        now = datetime.now(UTC)
        started = self._window_started.setdefault(key, now)
        if now - started > timedelta(hours=1):
            self._counts[key] = 0
            self._window_started[key] = now
        if self._counts[key] >= self._per_hour:
            return False
        self._counts[key] += 1
        return True


def slack_message(
    *,
    fallback: str,
    title: str,
    fields: list[tuple[str, str]],
    sections: list[str],
    footer: str,
) -> dict:
    return {
        "text": fallback,
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{label}:*\n{value}"} for label, value in fields
                ],
            },
            *({"type": "section", "text": {"type": "mrkdwn", "text": text}} for text in sections),
            {"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]},
        ],
    }


def alert_host() -> str:
    return os.environ.get("HOSTNAME", socket.gethostname())


def alert_footer(timestamp: str, host: str, correlation_id: str) -> str:
    return f"{timestamp} | host: {host} | Correlation: `{correlation_id}`"


_task_budget = SlackAlertBudget(TASK_ALERTS_PER_HOUR)


def _get_sync_client() -> httpx.Client:
    global _sync_client
    if _sync_client is None or _sync_client.is_closed:
        _sync_client = httpx.Client(timeout=5.0)
    return _sync_client


def alert_task_failed_permanently(
    *,
    webhook_url: str,
    service: str,
    environment: str,
    task_name: str,
    task_id: str,
    correlation_id: str,
    error_type: str,
) -> None:
    if not webhook_url or not _task_budget.allow(f"{service}:task:{task_name}"):
        return
    message = slack_message(
        fallback=f"{service} task failed permanently ({environment})",
        title=f"{service} — task failed permanently",
        fields=[
            ("Env", environment),
            ("Task", f"`{task_name}`"),
            ("Error", error_type),
            ("Task id", f"`{task_id}`"),
        ],
        sections=[],
        footer=alert_footer(
            datetime.now(UTC).isoformat(timespec="seconds"), alert_host(), correlation_id
        ),
    )
    try:
        _get_sync_client().post(webhook_url, json=message).raise_for_status()
    except Exception as exc:
        logger.error("Failed to send Slack alert: %s", exc)
