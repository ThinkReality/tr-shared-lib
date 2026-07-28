"""Generic ``httpx.MockTransport`` route builder.

The one real mechanism ``tr_shared.testing.stubs`` standardizes on: routes are
matched against the REAL ``httpx.AsyncClient``/``httpx.Client`` a service's
production code already builds and calls, not against patched internals or a
patched ``httpx.AsyncClient`` class. That's what makes it a fake of the *contract*
(method, path, response shape) rather than a fake of *how a particular client
happens to be implemented* — patched-internals mocks break the moment the client's
internal structure changes even if the real HTTP contract hasn't.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    import httpx

__all__ = ["MockTransportBuilder", "RecordedRequest"]


@dataclass
class RecordedRequest:
    """A request the built transport actually received — for call-count/payload
    assertions, the same thing a ``mock_post.call_args`` inspection gives you."""

    method: str
    url: str
    json: Any
    headers: dict[str, str]


@dataclass
class _Route:
    method: str
    path_pattern: re.Pattern[str]
    responder: Callable[["httpx.Request"], "httpx.Response"]


class MockTransportBuilder:
    """Register routes, then ``.build()`` an ``httpx.MockTransport``.

    Usage::

        builder = MockTransportBuilder()
        builder.route("POST", r"/oauth/token$", json={"access_token": "t", "expires_in": 3600})
        builder.route("GET", r"/listings/(?P<id>[\\w-]+)$", json=lambda m: {"id": m.group("id")})
        transport = builder.build()
        client = httpx.AsyncClient(transport=transport, base_url="https://example.test")

    ``builder.requests`` records every request the transport actually received, in
    order — the shared equivalent of inspecting ``mock_post.call_args_list``.
    """

    def __init__(self) -> None:
        self._routes: list[_Route] = []
        self.requests: list[RecordedRequest] = []

    def route(
        self,
        method: str,
        path_pattern: str,
        *,
        json: Any | Callable[[re.Match[str]], Any] | None = None,
        status_code: int = 200,
        handler: Callable[["httpx.Request", re.Match[str]], "httpx.Response"]
        | None = None,
    ) -> "MockTransportBuilder":
        """Register a route. Either pass ``json``/``status_code`` for the common
        case, or a full ``handler(request, match) -> httpx.Response`` for anything
        that needs request-dependent behaviour (error injection, pagination)."""
        import httpx

        compiled = re.compile(path_pattern)

        def _default_responder(request: "httpx.Request") -> "httpx.Response":
            match = compiled.search(request.url.path)
            assert match is not None  # route() already matched to get here
            if handler is not None:
                return handler(request, match)
            body = json(match) if callable(json) else json
            return httpx.Response(status_code, json=body)

        self._routes.append(_Route(method.upper(), compiled, _default_responder))
        return self

    def build(self) -> "httpx.MockTransport":
        import httpx

        def _dispatch(request: "httpx.Request") -> "httpx.Response":
            for candidate in self._routes:
                if candidate.method != request.method:
                    continue
                if not candidate.path_pattern.search(request.url.path):
                    continue
                self.requests.append(
                    RecordedRequest(
                        method=request.method,
                        url=str(request.url),
                        json=_safe_json(request),
                        headers=dict(request.headers),
                    )
                )
                return candidate.responder(request)
            raise AssertionError(
                f"MockTransportBuilder: no route registered for "
                f"{request.method} {request.url.path} — routes: "
                f"{[(r.method, r.path_pattern.pattern) for r in self._routes]}"
            )

        return httpx.MockTransport(_dispatch)


def _safe_json(request: "httpx.Request") -> Any:
    if not request.content:
        return None
    try:
        import json as _json

        return _json.loads(request.content)
    except ValueError:
        return None
