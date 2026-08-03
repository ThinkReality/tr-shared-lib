"""Shared API monitoring — OpenTelemetry + provider abstraction.

Prometheus / OTLP / Loki only. The "Layer 2" half — a PersistenceMiddleware that
buffered every request into Redis, Celery tasks that flushed and aggregated it into a
separate ``monitoring`` Postgres schema, and the SQLAlchemy models for that schema —
was deleted 2026-08-03. It never ran: every part of it was gated on
``MONITORING_DB_URL``, which was set in no ``.env`` and no ``.env.example`` in the
workspace, so the tasks logged "skipping" hourly and the middleware was never
installed. Prometheus + Grafana already covered the same ground.
"""

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
from tr_shared.monitoring.setup import setup_monitoring

__all__ = [
    "LogProvider",
    "LogProviderInterface",
    "MetricsProvider",
    "MetricsProviderInterface",
    "MonitoringProviderFactory",
    "TraceProvider",
    "TraceProviderInterface",
    "LokiHandler",
    "MetricsMiddleware",
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
