"""Rate limiter exceptions."""

from tr_shared.rate_limiter.schemas import RateLimitInfo


class RateLimitExceeded(Exception):
    """Raised when a rate limit is exceeded.

    Attributes:
        info: The aggregated rate limit info with per-window results.
        retry_after: Seconds until the client may retry.
    """

    def __init__(self, info: RateLimitInfo, retry_after: int = 0) -> None:
        self.info = info
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded (retry after {retry_after}s)")
