"""Fails the day the pinned redis-py ships PR #4288, so the mirrored write guard is
deleted instead of silently diverging from upstream."""

import inspect

from redis.asyncio.connection import Connection

UPSTREAM_GUARD_MESSAGE = "Connection closed by the server before write"


def test_pinned_redis_py_still_lacks_the_write_guard():
    assert UPSTREAM_GUARD_MESSAGE not in inspect.getsource(Connection._send_packed_command), (
        "redis-py now carries PR #4288. Do this, in order: "
        "(1) delete ProxySafeConnection._send_packed_command and its socket_timeout "
        "precondition in __init__ (upstream routes every write through the guarded "
        "method now); (2) keep can_read_destructive — upstream has no checkout-time "
        "guard for a reset transport; (3) raise the redis floor in pyproject to the "
        "first release containing the fix; (4) delete this test."
    )
