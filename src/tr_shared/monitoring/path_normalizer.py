"""
Path normalization for low-cardinality Prometheus metrics.

Extracted from tr-cms-service/app/core/telemetry.py (lines 52-75).
Converts dynamic path segments (UUIDs, numeric IDs) to ``{id}``
placeholders so Prometheus doesn't create unbounded label series.

Usage::

    from tr_shared.monitoring import normalize_path

    normalize_path("/api/v1/blogs/550e8400-e29b-41d4-a716-446655440000")
    # -> "/api/v1/blogs/{id}"

    normalize_path("/api/v1/users/123/posts/456")
    # -> "/api/v1/users/{id}/posts/{id}"
"""

import re

# Compiled at module level — not per-call
_UUID_RE = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_NUMERIC_ID_RE = re.compile(r"/\d+(?=/|$)")


def normalize_path(path: str) -> str:
    """
    Normalize an API path to reduce metric cardinality.

    Replaces UUIDs and numeric IDs with ``{id}``.

    Args:
        path: Original request path.

    Returns:
        Normalized path with placeholders.
    """
    path = _UUID_RE.sub("/{id}", path)
    path = _NUMERIC_ID_RE.sub("/{id}", path)
    return path
