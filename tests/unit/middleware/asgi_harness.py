from collections.abc import Iterable


def http_scope(
    path: str = "/", headers: Iterable[tuple[str, str]] = (), client=("10.1.2.3", 5000)
) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": client,
        "server": ("test", 80),
        "scheme": "http",
    }


async def receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


async def call(app, scope: dict) -> list[dict]:
    messages: list[dict] = []

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages


def response_header(messages: list[dict], name: str) -> str | None:
    start = next(m for m in messages if m["type"] == "http.response.start")
    for key, value in start["headers"]:
        if key.decode().lower() == name.lower():
            return value.decode()
    return None
