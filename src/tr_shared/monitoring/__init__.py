"""Shared API monitoring — OpenTelemetry + provider abstraction + Layer 2 persistence."""

from tr_shared.monitoring.factory import (
    LogProvider,
    MetricsProvider,
    MonitoringProviderFactory,
    TraceProvider,
)
from tr_shared.monitoring.interfaces import (
    LogProviderInterface,
    MetricsProviderInterface,
    TraceProviderInterface,
)
from tr_shared.monitoring.loki_handler import LokiHandler
from tr_shared.monitoring.middleware import MetricsMiddleware
from tr_shared.monitoring.path_normalizer import normalize_path
from tr_shared.monitoring.persistence import PersistenceMiddleware
from tr_shared.monitoring.prometheus_client import PrometheusClient
from tr_shared.monitoring.setup import setup_monitoring

__all__ = [
    # Provider abstraction
    "LogProvider",
    "LogProviderInterface",
    "MetricsProvider",
    "MetricsProviderInterface",
    "MonitoringProviderFactory",
    "TraceProvider",
    "TraceProviderInterface",
    # Existing public API
    "LokiHandler",
    "MetricsMiddleware",
    "PersistenceMiddleware",
    "PrometheusClient",
    "normalize_path",
    "setup_monitoring",
    # Opt-in instrumentation (lazy — require db / celery extras respectively)
    "setup_db_instrumentation",
    "setup_celery_instrumentation",
]

_LAZY_IMPORTS = {
    "setup_db_instrumentation": "tr_shared.monitoring.db_instrumentation",
    "setup_celery_instrumentation": "tr_shared.monitoring.celery_instrumentation",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        mod = importlib.import_module(_LAZY_IMPORTS[name])
        obj = getattr(mod, name)
        # Cache in module namespace so the next access is a normal attribute lookup.
        globals()[name] = obj
        return obj
    raise AttributeError(f"module 'tr_shared.monitoring' has no attribute {name!r}")
