"""Tests for tr_shared.events.retry_policy."""

from tr_shared.events.retry_policy import RetryPolicy


class TestRetryPolicy:
    def test_defaults(self):
        rp = RetryPolicy()
        assert rp.max_retries == 3
        assert rp.backoff_base == 2
        assert rp.max_backoff == 30

    def test_delay_exponential(self):
        rp = RetryPolicy(backoff_base=2, max_backoff=30)
        assert rp.delay_for(1) == 2
        assert rp.delay_for(2) == 4
        assert rp.delay_for(3) == 8

    def test_delay_capped_at_max(self):
        rp = RetryPolicy(backoff_base=2, max_backoff=10)
        assert rp.delay_for(10) == 10

    def test_zero_retries_means_no_retry(self):
        rp = RetryPolicy(max_retries=0)
        assert rp.max_retries == 0
