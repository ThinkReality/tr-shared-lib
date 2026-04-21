"""Tests for tr_shared.db.migrations.concurrent_index."""

from contextlib import contextmanager

import pytest

from tr_shared.db.migrations import concurrent_index_context


class _FakeContext:
    def __init__(self, expose_autocommit: bool = True) -> None:
        self.autocommit_entered = False
        self.autocommit_exited = False
        if expose_autocommit:
            self.autocommit_block = self._autocommit_block

    @contextmanager
    def _autocommit_block(self):
        self.autocommit_entered = True
        try:
            yield
        finally:
            self.autocommit_exited = True


class _FakeOp:
    def __init__(self, ctx: _FakeContext | None) -> None:
        self._ctx = ctx

    def get_context(self):
        if self._ctx is None:
            raise RuntimeError("no migration context")
        return self._ctx


class TestConcurrentIndexContext:
    def test_enters_and_exits_autocommit_block(self):
        ctx = _FakeContext()
        op = _FakeOp(ctx)
        with concurrent_index_context(op):
            assert ctx.autocommit_entered is True
            assert ctx.autocommit_exited is False
        assert ctx.autocommit_exited is True

    def test_raises_outside_migration_context(self):
        op = _FakeOp(None)
        with pytest.raises(RuntimeError, match="Alembic migration op context"):
            with concurrent_index_context(op):
                pass

    def test_raises_when_autocommit_block_missing(self):
        ctx = _FakeContext(expose_autocommit=False)
        op = _FakeOp(ctx)
        with pytest.raises(RuntimeError, match="autocommit_block"):
            with concurrent_index_context(op):
                pass

    def test_yield_value_is_none(self):
        ctx = _FakeContext()
        op = _FakeOp(ctx)
        with concurrent_index_context(op) as val:
            assert val is None
