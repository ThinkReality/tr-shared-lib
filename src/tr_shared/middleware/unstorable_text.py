import json
from collections.abc import Iterable
from email.message import Message as ContentType
from urllib.parse import parse_qsl

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tr_shared.schemas.error_envelope import build_error_envelope
from tr_shared.schemas.validators import unstorable_text_location

Location = tuple[str | int, ...]

_FORM = "application/x-www-form-urlencoded"


def _content_type(raw: str | None) -> ContentType | None:
    if not raw:
        return None
    parsed = ContentType()
    parsed["content-type"] = raw
    return parsed


def _is_json(content_type: ContentType | None) -> bool:
    if content_type is None:
        return True
    subtype = content_type.get_content_subtype()
    return content_type.get_content_maintype() == "application" and (
        subtype == "json" or subtype.endswith("+json")
    )


def _is_form(content_type: ContentType | None) -> bool:
    return content_type is not None and content_type.get_content_type() == _FORM


def _pairs_location(pairs: Iterable[tuple[str, str]]) -> Location | None:
    for name, value in pairs:
        if unstorable_text_location(name) is not None:
            return ()
        if unstorable_text_location(value) is not None:
            return (name,)
    return None


def _urlencoded_location(raw: bytes) -> Location | None:
    return _pairs_location(parse_qsl(raw.decode("latin-1"), keep_blank_values=True))


def _json_location(raw: bytes) -> Location | None:
    try:
        parsed = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return unstorable_text_location(parsed)


class UnstorableTextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if unstorable_text_location(scope["path"]) is not None:
            await self._reject(scope, receive, send, ("path",))
            return
        query = _urlencoded_location(scope["query_string"])
        if query is not None:
            await self._reject(scope, receive, send, ("query", *query))
            return

        content_type = _content_type(Headers(scope=scope).get("content-type"))
        if _is_json(content_type):
            body_location = _json_location
        elif _is_form(content_type):
            body_location = _urlencoded_location
        else:
            await self.app(scope, receive, send)
            return

        messages: list[Message] = []
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request" or not message.get("more_body", False):
                break

        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.request")
        location = body_location(body)
        if location is not None:
            await self._reject(scope, receive, send, ("body", *location))
            return

        async def replay() -> Message:
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, loc: Location) -> None:
        response = JSONResponse(
            status_code=422,
            content=build_error_envelope(
                message="Validation failed",
                code="VALIDATION_ERROR",
                correlation_id=scope.get("state", {}).get("correlation_id"),
                fields=[
                    {
                        "type": "string_unstorable",
                        "loc": list(loc),
                        "msg": "Text contains a NUL or unpaired surrogate character",
                    }
                ],
            ),
        )
        await response(scope, receive, send)
