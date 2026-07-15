"""
Path normalization for low-cardinality Prometheus metrics.

Converts dynamic path segments (UUIDs, numeric IDs) to ``{id}``
placeholders so Prometheus doesn't create unbounded label series.
"""

import re

# Compiled at module level — not per-call
_UUID_RE = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_NUMERIC_ID_RE = re.compile(r"/\d+(?=/|$)")


def normalize_path(path: str) -> str:
    """Normalize an API path to reduce metric cardinality."""
    path = _UUID_RE.sub("/{id}", path)
    path = _NUMERIC_ID_RE.sub("/{id}", path)
    return path
