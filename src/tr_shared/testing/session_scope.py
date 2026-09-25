"""Every route's request session must be function-scoped, so it closes before the response."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator
from typing import Any


def _session_scopes(
    dependant: Any, dependencies: Collection[Callable[..., Any]]
) -> Iterator[str | None]:
    for sub in dependant.dependencies:
        if sub.call in dependencies:
            yield sub.scope
        yield from _session_scopes(sub, dependencies)


def assert_session_dependencies_are_function_scoped(
    app: Any, dependencies: Collection[Callable[..., Any]]
) -> None:
    scanned = 0
    offenders = []
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        scopes = set(_session_scopes(dependant, dependencies))
        scanned += bool(scopes)
        if scopes - {"function"}:
            offenders.append(f"{sorted(getattr(route, 'methods', None) or [])} {route.path}")

    assert scanned, "no route depends on a session — the scan is not seeing the dependency"
    assert not offenders, 'session dependency not scope="function":\n' + "\n".join(
        sorted(offenders)
    )
