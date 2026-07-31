"""Monitoring provider factory — config-driven adapter selection.

Follows the same pattern as ``cache/factory.py``: enum of providers,
static factory methods, import-on-demand to avoid pulling unused deps.

Adding a provider (worked example: a BetterStack log backend)
-------------------------------------------------------------
No core changes are needed — that is what this factory exists for:

1. Create ``monitoring/adapters/betterstack_log.py`` implementing
   ``LogProviderInterface`` (one method, ``create_handler``).
2. Add ``BETTERSTACK = "betterstack"`` to the ``LogProvider`` enum below.
3. Add an import-on-demand branch in ``create_log_provider`` — mirror the
   ``LogProvider.LOKI`` branch exactly; the import must stay inside the branch
   so the dependency is never pulled for services that do not use it.
4. Declare the optional extra in ``pyproject.toml``:
   ``monitoring-betterstack = ["betterstack-sdk>=..."]``.
5. Callers pass ``setup_monitoring(log_provider="betterstack")``.

The same five steps apply to a metrics or trace provider via
``MetricsProviderInterface`` / ``TraceProviderInterface``.

One caveat step 5 hides: a provider needing its own configuration (the way
Loki needs ``loki_url`` and OTLP needs ``otlp_endpoint``) also requires new
kwargs on both ``create_*_provider`` here and ``setup_monitoring``. Only a
provider configured purely by environment is truly zero-touch.

Note the ``provider`` arguments are typed ``str``, not these enums, so a typo
is not caught at the call site — it raises from the factory's terminal
``ValueError``.
"""

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tr_shared.monitoring.interfaces import (
        LogProviderInterface,
        MetricsProviderInterface,
        TraceProviderInterface,
    )

logger = logging.getLogger(__name__)


class MetricsProvider(str, Enum):
    """Supported metrics providers."""

    PROMETHEUS = "prometheus"
    NOOP = "noop"


class LogProvider(str, Enum):
    """Supported log shipping providers."""

    LOKI = "loki"
    NOOP = "noop"


class TraceProvider(str, Enum):
    """Supported trace export providers."""

    OTLP = "otlp"
    NOOP = "noop"


class MonitoringProviderFactory:
    """Factory for creating monitoring provider instances.

    All adapters are imported on-demand so that unused provider
    dependencies are never loaded.
    """

    @staticmethod
    def create_metrics_provider(
        provider: str = "prometheus",
    ) -> "MetricsProviderInterface":
        """Create a metrics provider adapter.

        Args:
            provider: ``"prometheus"`` or ``"noop"``.
        """
        provider_lower = provider.lower()
        logger.info("Initializing metrics provider: %s", provider_lower)

        if provider_lower == MetricsProvider.PROMETHEUS:
            from tr_shared.monitoring.adapters.prometheus_metrics import (
                PrometheusMetricsAdapter,
            )

            return PrometheusMetricsAdapter()

        if provider_lower == MetricsProvider.NOOP:
            from tr_shared.monitoring.adapters.noop import NoopMetricsAdapter

            return NoopMetricsAdapter()

        raise ValueError(
            f"Unsupported metrics provider: {provider}. "
            f"Use one of: {[p.value for p in MetricsProvider]}"
        )

    @staticmethod
    def create_log_provider(
        provider: str = "loki",
        *,
        loki_url: str = "",
        batch_size: int = 100,
        flush_interval: float = 5.0,
    ) -> "LogProviderInterface":
        """Create a log shipping provider adapter.

        Args:
            provider: ``"loki"`` or ``"noop"``.
            loki_url: Loki push API URL (required for ``"loki"``).
            batch_size: Log batch size before flush.
            flush_interval: Max seconds between flushes.
        """
        provider_lower = provider.lower()
        logger.info("Initializing log provider: %s", provider_lower)

        if provider_lower == LogProvider.LOKI:
            from tr_shared.monitoring.adapters.loki_log import LokiLogAdapter

            return LokiLogAdapter(
                url=loki_url,
                batch_size=batch_size,
                flush_interval=flush_interval,
            )

        if provider_lower == LogProvider.NOOP:
            from tr_shared.monitoring.adapters.noop import NoopLogAdapter

            return NoopLogAdapter()

        raise ValueError(
            f"Unsupported log provider: {provider}. Use one of: {[p.value for p in LogProvider]}"
        )

    @staticmethod
    def create_trace_provider(
        provider: str = "otlp",
        *,
        otlp_endpoint: str = "",
    ) -> "TraceProviderInterface":
        """Create a trace export provider adapter.

        Args:
            provider: ``"otlp"`` or ``"noop"``.
            otlp_endpoint: OTLP gRPC endpoint (required for ``"otlp"``).
        """
        provider_lower = provider.lower()
        logger.info("Initializing trace provider: %s", provider_lower)

        if provider_lower == TraceProvider.OTLP:
            from tr_shared.monitoring.adapters.otlp_trace import OtlpTraceAdapter

            return OtlpTraceAdapter(endpoint=otlp_endpoint)

        if provider_lower == TraceProvider.NOOP:
            from tr_shared.monitoring.adapters.noop import NoopTraceAdapter

            return NoopTraceAdapter()

        raise ValueError(
            f"Unsupported trace provider: {provider}. "
            f"Use one of: {[p.value for p in TraceProvider]}"
        )
