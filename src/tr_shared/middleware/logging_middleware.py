import time

import structlog
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tr_shared.contracts.headers import HttpHeader

logger = structlog.get_logger(__name__)

DEFAULT_EXCLUDED_PATHS: set[str] = {
    "/",
    "/health",
    "/health/ready",
    "/health/live",
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/health/live",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
}


class LoggingMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        service_name: str = "unknown",
        excluded_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self.service_name = service_name
        self.excluded_paths = excluded_paths or DEFAULT_EXCLUDED_PATHS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        if connection.url.path in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        fields = self._request_fields(connection)
        status_code = 500

        async def send_recording_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        logger.info("request_started", service=self.service_name, **fields)
        try:
            await self.app(scope, receive, send_recording_status)
        except Exception as exc:
            logger.exception(
                "request_failed",
                service=self.service_name,
                duration_ms=self._elapsed_ms(start),
                error_type=type(exc).__name__,
                error_summary=str(exc)[:200],
                **fields,
            )
            raise

        log = logger.info if status_code < 400 else logger.warning
        log(
            "request_completed",
            service=self.service_name,
            status_code=status_code,
            duration_ms=self._elapsed_ms(start),
            **fields,
        )

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)

    @staticmethod
    def _request_fields(connection: HTTPConnection) -> dict:
        fields: dict = {
            "method": connection.scope["method"],
            "path": connection.url.path,
        }
        if connection.query_params:
            fields["query_string"] = str(connection.query_params)

        forwarded = connection.headers.get(HttpHeader.FORWARDED_FOR.value)
        if forwarded:
            fields["client_ip"] = forwarded.split(",")[0].strip()
        elif connection.client:
            fields["client_ip"] = connection.client.host

        user_agent = connection.headers.get("User-Agent")
        if user_agent:
            fields["user_agent"] = user_agent

        correlation_id = connection.scope.get("state", {}).get("correlation_id")
        if correlation_id:
            fields["correlation_id"] = correlation_id

        tenant_id = connection.headers.get(HttpHeader.TENANT_ID.value)
        if tenant_id:
            fields["tenant_id"] = tenant_id

        return fields
