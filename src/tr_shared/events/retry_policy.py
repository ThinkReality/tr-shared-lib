"""Configurable retry policy for event processing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Controls retry behaviour for failed event handlers.

    Set ``max_retries=0`` to disable retries (failed events go straight to DLQ).
    """

    max_retries: int = 3
    backoff_base: int = 2
    max_backoff: int = 30

    def delay_for(self, attempt: int) -> float:
        """Calculate backoff delay in seconds for the given attempt number."""
        return min(self.backoff_base**attempt, self.max_backoff)
