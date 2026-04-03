"""Dead-letter queue handler for failed/malformed events."""

import json
import logging
import time

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class DeadLetterHandler:
    """Moves failed messages to a dead-letter Redis Stream."""

    def __init__(
        self,
        redis_client: redis.Redis,
        source_stream: str,
        consumer_group: str,
        maxlen: int = 10_000,
    ) -> None:
        self._redis = redis_client
        self._dl_stream = f"{source_stream}_dead_letter"
        self._consumer_group = consumer_group
        self._maxlen = maxlen

    async def move(
        self,
        message_id: str,
        message_data: dict[str, str],
        reason: str,
    ) -> None:
        try:
            entry = {
                "original_message_id": message_id,
                "original_stream": self._dl_stream.replace("_dead_letter", ""),
                "consumer_group": self._consumer_group,
                "failure_reason": reason,
                "timestamp": str(time.time()),
                "original_data": json.dumps(message_data),
            }
            await self._redis.xadd(self._dl_stream, entry, maxlen=self._maxlen)
            logger.warning("Moved message %s to DLQ: %s", message_id, reason)
        except Exception:
            logger.exception("Failed to move message %s to DLQ", message_id)
            raise
