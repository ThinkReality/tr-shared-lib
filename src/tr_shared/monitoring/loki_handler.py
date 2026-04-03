"""
Python logging handler that pushes logs to Grafana Loki.

Uses Loki's /loki/api/v1/push HTTP endpoint directly (no Promtail needed).
Labels are kept low-cardinality (service, environment, level).
High-cardinality fields (tenant_id, correlation_id, user_id) stay in the
JSON log line and can be queried via LogQL: {service="..."} | json | tenant_id="..."

Usage::

    from tr_shared.monitoring.loki_handler import LokiHandler

    handler = LokiHandler(
        url="http://loki.railway.internal:3100/loki/api/v1/push",
        labels={"service": "crm-backend", "environment": "production"},
    )
    logging.getLogger().addHandler(handler)
"""

import json
import logging
import threading
import time
from collections import deque
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LokiHandler(logging.Handler):
    """
    Logging handler that batches and pushes log entries to Loki.

    Batches logs in memory and flushes every ``flush_interval`` seconds
    or when ``batch_size`` is reached, whichever comes first.

    Args:
        url: Loki push API endpoint (e.g. ``http://loki:3100/loki/api/v1/push``).
        labels: Static labels attached to every log stream.
            Keep these low-cardinality (service, environment, level).
        batch_size: Number of log entries to buffer before flushing.
        flush_interval: Maximum seconds between flushes.
    """

    def __init__(
        self,
        url: str,
        labels: dict[str, str] | None = None,
        batch_size: int = 100,
        flush_interval: float = 5.0,
    ) -> None:
        super().__init__()
        self.url = url
        self.static_labels = labels or {}
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self._buffer: deque[tuple[str, dict[str, str], str]] = deque()
        self._lock = threading.Lock()

        # Background flush thread
        self._flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
        self._flush_thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        """Buffer a log record for sending to Loki."""
        try:
            # Build the JSON log line (high-cardinality fields stay here)
            log_entry = self._format_record(record)

            # Nanosecond timestamp for Loki
            ts_ns = str(int(record.created * 1e9))

            # Labels: static + level (low-cardinality only)
            labels = {**self.static_labels, "level": record.levelname.lower()}

            with self._lock:
                self._buffer.append((ts_ns, labels, log_entry))

            if len(self._buffer) >= self.batch_size:
                self._flush()

        except Exception:
            self.handleError(record)

    def _format_record(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string for Loki log line."""
        entry: dict[str, Any] = {
            "message": record.getMessage(),
            "logger": record.name,
            "level": record.levelname,
        }

        # Include structured extra fields (tenant_id, correlation_id, etc.)
        if hasattr(record, "tenant_id"):
            entry["tenant_id"] = record.tenant_id
        if hasattr(record, "correlation_id"):
            entry["correlation_id"] = record.correlation_id
        if hasattr(record, "user_id"):
            entry["user_id"] = record.user_id

        # Include any other extra fields from the record
        standard_attrs = logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
        for key, value in record.__dict__.items():
            if key not in standard_attrs and key not in entry and not key.startswith("_"):
                try:
                    json.dumps(value)  # Only include JSON-serializable values
                    entry[key] = value
                except (TypeError, ValueError):
                    entry[key] = str(value)

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.format(record) if self.formatter else str(record.exc_info[1])

        return json.dumps(entry, default=str)

    def _flush(self) -> None:
        """Send buffered logs to Loki."""
        with self._lock:
            if not self._buffer:
                return
            entries = list(self._buffer)
            self._buffer.clear()

        # Group by label set
        streams: dict[str, dict[str, Any]] = {}
        for ts_ns, labels, line in entries:
            label_key = json.dumps(labels, sort_keys=True)
            if label_key not in streams:
                streams[label_key] = {
                    "stream": labels,
                    "values": [],
                }
            streams[label_key]["values"].append([ts_ns, line])

        payload = {"streams": list(streams.values())}

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    self.url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "Loki push failed: %s %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except Exception as e:
            # Don't let Loki failures break the application
            logger.warning("Failed to push logs to Loki: %s", e)

    def _periodic_flush(self) -> None:
        """Background thread: flush buffer periodically."""
        while True:
            time.sleep(self.flush_interval)
            try:
                self._flush()
            except Exception:
                pass

    def close(self) -> None:
        """Flush remaining logs and close the handler."""
        self._flush()
        super().close()
