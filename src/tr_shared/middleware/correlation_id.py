import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tr_shared.contracts.headers import HttpHeader, is_valid_correlation_id


class CorrelationIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(HttpHeader.CORRELATION_ID.value)
        correlation_id = (
            incoming if incoming and is_valid_correlation_id(incoming) else str(uuid.uuid4())
        )
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_correlation_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                MutableHeaders(scope=message)[HttpHeader.CORRELATION_ID.value] = correlation_id
            await send(message)

        with structlog.contextvars.bound_contextvars(correlation_id=correlation_id):
            await self.app(scope, receive, send_with_correlation_id)
