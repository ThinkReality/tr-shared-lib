import asyncio
import socket
import struct
from collections.abc import Coroutine
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class Relay:
    def __init__(self, target_url: str) -> None:
        parts = urlsplit(target_url)
        self._target = (parts.hostname, parts.port)
        self._parts = parts
        self._client_writers: set[asyncio.StreamWriter] = set()
        self._flowing: set[asyncio.Event] = set()
        self._server: asyncio.AbstractServer | None = None
        self.url = ""

    async def __aenter__(self) -> "Relay":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        userinfo = self._parts.netloc.rsplit("@", 1)[0] + "@" if "@" in self._parts.netloc else ""
        self.url = urlunsplit(self._parts._replace(netloc=f"{userinfo}127.0.0.1:{port}"))
        return self

    async def __aexit__(self, *exc: object) -> None:
        for writer in list(self._client_writers):
            writer.close()
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._client_writers.add(writer)
        flowing = asyncio.Event()
        flowing.set()
        self._flowing.add(flowing)
        up_reader, up_writer = await asyncio.open_connection(*self._target)
        try:
            await asyncio.gather(
                self._pump(reader, up_writer, flowing), self._pump(up_reader, writer, flowing)
            )
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            up_writer.close()
            writer.close()
            self._client_writers.discard(writer)
            self._flowing.discard(flowing)

    @staticmethod
    async def _pump(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter, flowing: asyncio.Event
    ) -> None:
        while data := await reader.read(65536):
            await flowing.wait()
            writer.write(data)
            await writer.drain()
        writer.close()

    def reset_clients(self) -> None:
        for writer in list(self._client_writers):
            if writer.transport.is_closing():
                continue
            sock = writer.get_extra_info("socket")
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            writer.transport.abort()

    def freeze(self) -> None:
        for flowing in self._flowing:
            flowing.clear()


async def finish_within(seconds: float, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    task = asyncio.create_task(coro)
    done, _ = await asyncio.wait({task}, timeout=seconds)
    while not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=0.1)
    assert done, f"still running after {seconds} s"
    return task
