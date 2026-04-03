"""Loki log adapter — delegates to existing LokiHandler."""

import logging

from tr_shared.monitoring.interfaces import LogProviderInterface


class LokiLogAdapter(LogProviderInterface):
    """Wraps the existing LokiHandler for log shipping to Grafana Loki."""

    def __init__(
        self,
        url: str,
        batch_size: int = 100,
        flush_interval: float = 5.0,
    ) -> None:
        self.url = url
        self.batch_size = batch_size
        self.flush_interval = flush_interval

    def create_handler(
        self, service_name: str, labels: dict[str, str]
    ) -> logging.Handler:
        from tr_shared.monitoring.loki_handler import LokiHandler

        return LokiHandler(
            url=self.url,
            labels={"service": service_name, **labels},
            batch_size=self.batch_size,
            flush_interval=self.flush_interval,
        )
