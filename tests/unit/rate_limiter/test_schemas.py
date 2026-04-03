"""Tests for rate_limiter Pydantic schemas and enums."""

import pytest

from tr_shared.rate_limiter.schemas import (
    Algorithm,
    FailMode,
    RateLimitConfig,
    RateLimitInfo,
    RateLimitResult,
    WindowConfig,
)


class TestAlgorithmEnum:
    def test_fixed_window_value(self):
        assert Algorithm.FIXED_WINDOW == "fixed_window"

    def test_sliding_window_value(self):
        assert Algorithm.SLIDING_WINDOW == "sliding_window"

    def test_is_string_enum(self):
        assert isinstance(Algorithm.FIXED_WINDOW, str)


class TestFailModeEnum:
    def test_open_value(self):
        assert FailMode.OPEN == "open"

    def test_closed_value(self):
        assert FailMode.CLOSED == "closed"

    def test_is_string_enum(self):
        assert isinstance(FailMode.OPEN, str)


class TestWindowConfig:
    def test_defaults(self):
        wc = WindowConfig()
        assert wc.limit == 100
        assert wc.window_seconds == 60

    def test_custom_values(self):
        wc = WindowConfig(limit=10, window_seconds=30)
        assert wc.limit == 10
        assert wc.window_seconds == 30

    def test_large_limit(self):
        wc = WindowConfig(limit=10_000, window_seconds=3600)
        assert wc.limit == 10_000
        assert wc.window_seconds == 3600


class TestRateLimitConfig:
    def test_defaults(self):
        cfg = RateLimitConfig()
        assert len(cfg.windows) == 1
        assert cfg.windows[0].limit == 100
        assert cfg.windows[0].window_seconds == 60
        assert cfg.algorithm == Algorithm.FIXED_WINDOW
        assert cfg.fail_mode == FailMode.OPEN
        assert cfg.methods is None

    def test_custom_algorithm(self):
        cfg = RateLimitConfig(algorithm=Algorithm.SLIDING_WINDOW)
        assert cfg.algorithm == Algorithm.SLIDING_WINDOW

    def test_custom_fail_mode(self):
        cfg = RateLimitConfig(fail_mode=FailMode.CLOSED)
        assert cfg.fail_mode == FailMode.CLOSED

    def test_multiple_windows(self):
        cfg = RateLimitConfig(
            windows=[
                WindowConfig(limit=100, window_seconds=60),
                WindowConfig(limit=1000, window_seconds=3600),
            ]
        )
        assert len(cfg.windows) == 2
        assert cfg.windows[0].window_seconds == 60
        assert cfg.windows[1].window_seconds == 3600

    def test_methods_filter(self):
        cfg = RateLimitConfig(methods=["POST", "PUT"])
        assert cfg.methods == ["POST", "PUT"]

    def test_key_prefix_default(self):
        cfg = RateLimitConfig()
        assert cfg.key_prefix == "rl"

    def test_custom_key_prefix(self):
        cfg = RateLimitConfig(key_prefix="webhook")
        assert cfg.key_prefix == "webhook"


class TestRateLimitResult:
    def test_allowed_result(self):
        r = RateLimitResult(allowed=True, limit=100, remaining=99, reset_at=9_999_999)
        assert r.allowed is True
        assert r.remaining == 99
        assert r.retry_after == 0

    def test_blocked_result(self):
        r = RateLimitResult(
            allowed=False, limit=100, remaining=0, reset_at=9_999_999, retry_after=30
        )
        assert r.allowed is False
        assert r.remaining == 0
        assert r.retry_after == 30

    def test_retry_after_default_zero(self):
        r = RateLimitResult(allowed=True, limit=10, remaining=9, reset_at=1)
        assert r.retry_after == 0


class TestRateLimitInfo:
    def test_default_not_blocked(self):
        info = RateLimitInfo()
        assert info.is_blocked is False
        assert info.results == []

    def test_blocked_state(self):
        blocked = RateLimitResult(
            allowed=False, limit=10, remaining=0, reset_at=9_999_999, retry_after=30
        )
        info = RateLimitInfo(results=[blocked], is_blocked=True)
        assert info.is_blocked is True

    def test_with_multiple_results(self):
        r1 = RateLimitResult(allowed=True, limit=100, remaining=95, reset_at=9_999_999)
        r2 = RateLimitResult(
            allowed=False, limit=1000, remaining=0, reset_at=9_999_999, retry_after=60
        )
        info = RateLimitInfo(results=[r1, r2], is_blocked=True)
        assert len(info.results) == 2
        assert info.is_blocked is True

    def test_allowed_with_results(self):
        r = RateLimitResult(allowed=True, limit=100, remaining=80, reset_at=9_999_999)
        info = RateLimitInfo(results=[r], is_blocked=False)
        assert info.is_blocked is False
        assert len(info.results) == 1
