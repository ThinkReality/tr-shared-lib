"""Deterministic guards for ProxySafeConnection against a stub asyncio transport.

The stub stands in for the transport (an asyncio boundary), not for redis-py or
tr_shared. A reset proxy leg leaves ``transport.is_closing()`` True and the
reader carrying an exception while redis-py's ``is_connected`` still says True.
"""

from unittest import mock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from tr_shared.redis.connection import ProxySafeConnection, require_plain_redis_url


def _connection(*, closing: bool, reader_exc: BaseException | None = None) -> ProxySafeConnection:
    conn = ProxySafeConnection(socket_timeout=1, health_check_interval=0)
    writer = mock.Mock()
    writer.transport.is_closing.return_value = closing
    writer.drain = mock.AsyncMock()
    reader = mock.Mock()
    reader.exception.return_value = reader_exc
    conn._reader = reader
    conn._writer = writer
    conn._parser.can_read_destructive = mock.AsyncMock(return_value=False)
    return conn


class TestCheckoutGuard:
    async def test_closing_transport_raises_connection_error(self):
        conn = _connection(closing=True)
        with pytest.raises(RedisConnectionError, match="idle"):
            await conn.can_read_destructive()

    async def test_reader_exception_raises_connection_error(self):
        conn = _connection(closing=False, reader_exc=ConnectionResetError())
        with pytest.raises(RedisConnectionError, match="idle"):
            await conn.can_read_destructive()

    async def test_live_transport_falls_through_to_parser(self):
        conn = _connection(closing=False)
        assert await conn.can_read_destructive() is False
        conn._parser.can_read_destructive.assert_awaited_once()

    async def test_guard_does_not_await_before_transport_check(self):
        conn = _connection(closing=True)
        with pytest.raises(RedisConnectionError):
            await conn.can_read_destructive()
        conn._parser.can_read_destructive.assert_not_awaited()


class TestWriteGuard:
    async def test_closing_transport_raises_before_write(self):
        conn = _connection(closing=True)
        with pytest.raises(RedisConnectionError, match="before write") as exc_info:
            await conn.send_packed_command(b"PING", check_health=False)
        assert type(exc_info.value) is RedisConnectionError
        assert not conn.is_connected

    async def test_open_transport_writes(self):
        conn = _connection(closing=False)
        writer = conn._writer
        await conn.send_packed_command(b"PING", check_health=False)
        writer.writelines.assert_called_once_with([b"PING"])
        writer.drain.assert_awaited_once_with()

    @pytest.mark.parametrize(
        "leaked", [TypeError("'NoneType' object is not callable"), AttributeError("_add_writer")]
    )
    async def test_cpython_leaked_error_on_closing_transport_becomes_connection_error(self, leaked):
        conn = _connection(closing=False)
        writer = conn._writer

        def close_then_raise(_command):
            writer.transport.is_closing.return_value = True
            raise leaked

        writer.writelines.side_effect = close_then_raise
        with pytest.raises(RedisConnectionError, match="while writing") as exc_info:
            await conn.send_packed_command(b"PING", check_health=False)
        assert exc_info.value.__cause__ is leaked

    @pytest.mark.parametrize("leaked", [TypeError("bug"), AttributeError("bug")])
    async def test_leaked_error_on_open_transport_propagates(self, leaked):
        conn = _connection(closing=False)
        conn._writer.writelines.side_effect = leaked
        with pytest.raises(type(leaked)):
            await conn.send_packed_command(b"PING", check_health=False)


class TestSocketTimeoutPrecondition:
    @pytest.mark.parametrize("socket_timeout", [None, 0])
    def test_falsy_socket_timeout_is_rejected(self, socket_timeout):
        with pytest.raises(ValueError, match="socket_timeout"):
            ProxySafeConnection(socket_timeout=socket_timeout)


class TestRequirePlainRedisUrl:
    def test_redis_scheme_passes(self):
        require_plain_redis_url("redis://:pw@host:6379/0")

    @pytest.mark.parametrize("url", ["rediss://host:6379/0", "unix:///tmp/redis.sock?db=0"])
    def test_schemes_that_swap_connection_class_are_rejected(self, url):
        with pytest.raises(ValueError, match="only supports redis://"):
            require_plain_redis_url(url)
