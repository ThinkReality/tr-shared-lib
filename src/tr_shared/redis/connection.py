"""Pooled Redis connection that survives a proxy resetting it while idle.

Railway's TCP proxy resets idle client legs. asyncio reports a reset through
``reader.set_exception``, not EOF, so redis-py's checkout check
(``stream.at_eof()``) stays blind and the next write hits a closed transport —
``RuntimeError`` under uvloop, ``TypeError``/``AttributeError`` on CPython
≤ 3.13.9 — none of which the retry policy matches. Both guards below raise
redis's ``ConnectionError`` instead, which ``ConnectionPool.ensure_connection``
(checkout) and ``Retry`` (write) already reconnect on.
"""

import socket
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from redis.asyncio.connection import Connection
from redis.exceptions import ConnectionError

KEEPALIVE_IDLE_S = 60
KEEPALIVE_INTERVAL_S = 10
KEEPALIVE_COUNT = 3


def keepalive_options() -> dict[int, int]:
    """TCP probe options for ``socket_keepalive_options``, limited to constants this
    platform defines (macOS lacks TCP_KEEPIDLE); an unknown option makes redis-py
    close the connection at connect."""
    wanted = {
        "TCP_KEEPIDLE": KEEPALIVE_IDLE_S,
        "TCP_KEEPINTVL": KEEPALIVE_INTERVAL_S,
        "TCP_KEEPCNT": KEEPALIVE_COUNT,
    }
    return {
        option: value
        for name, value in wanted.items()
        if (option := getattr(socket, name, None)) is not None
    }


def require_plain_redis_url(url: str) -> None:
    """``rediss://`` and ``unix://`` make ``ConnectionPool.from_url`` inject their own
    ``connection_class``, silently replacing ProxySafeConnection."""
    scheme = urlsplit(url).scheme
    if scheme != "redis":
        raise ValueError(
            f"ProxySafeConnection only supports redis:// URLs, got {scheme}://; "
            "rediss:// and unix:// would silently drop the proxy guards"
        )


class ProxySafeConnection(Connection):
    def __init__(self, **kwargs: Any) -> None:
        if not kwargs.get("socket_timeout"):
            raise ValueError(
                "ProxySafeConnection requires a positive socket_timeout: redis-py only "
                "routes writes through _send_packed_command when socket_timeout is set"
            )
        super().__init__(**kwargs)

    async def can_read_destructive(self) -> bool:
        writer, reader = self._writer, self._reader
        if writer is not None and reader is not None:
            if writer.transport.is_closing() or reader.exception() is not None:
                raise ConnectionError("Connection closed by peer while idle")
        return bool(await super().can_read_destructive())

    # Mirrors redis-py PR #4288 (merged 2026-08-28, unreleased as of 8.1.0); delete when the pin carries it.
    async def _send_packed_command(self, command: Iterable[bytes]) -> None:
        writer = self._writer
        if writer is None or writer.transport.is_closing():
            raise ConnectionError("Connection closed by the server before write")
        try:
            writer.writelines(command)
            await writer.drain()
        except (TypeError, AttributeError) as e:
            if writer.transport.is_closing():
                raise ConnectionError("Connection closed by the server while writing") from e
            raise
