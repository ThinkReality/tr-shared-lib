"""Dead-letter queue handler for failed/malformed events."""

import json
import logging
import time

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Suffix appended to a source stream name to form its dead-letter stream.
# Single source of truth shared by the producer (this handler) and any reader
# (e.g. an admin DLQ inspection/replay service). Changing this changes where
# dead-lettered events are written AND read.
DEAD_LETTER_SUFFIX = "_dead_letter"

# Field keys written into each dead-letter stream entry by move().
# Readers MUST decode these exact keys — they are the wire contract.
DLQ_FIELD_ORIGINAL_MESSAGE_ID = "original_message_id"
DLQ_FIELD_ORIGINAL_STREAM = "original_stream"
DLQ_FIELD_CONSUMER_GROUP = "consumer_group"
DLQ_FIELD_FAILURE_REASON = "failure_reason"
DLQ_FIELD_TIMESTAMP = "timestamp"
DLQ_FIELD_ORIGINAL_DATA = "original_data"


def dead_letter_stream_name(source_stream: str) -> str:
    """Dead-letter stream name for a given source stream.

    The single canonical derivation — use this instead of hand-building the
    name so producer and readers never drift.
    """
    return f"{source_stream}{DEAD_LETTER_SUFFIX}"


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
        self._source_stream = source_stream
        self._dl_stream = dead_letter_stream_name(source_stream)
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
                DLQ_FIELD_ORIGINAL_MESSAGE_ID: message_id,
                DLQ_FIELD_ORIGINAL_STREAM: self._source_stream,
                DLQ_FIELD_CONSUMER_GROUP: self._consumer_group,
                DLQ_FIELD_FAILURE_REASON: reason,
                DLQ_FIELD_TIMESTAMP: str(time.time()),
                DLQ_FIELD_ORIGINAL_DATA: json.dumps(message_data),
            }
            await self._redis.xadd(self._dl_stream, entry, maxlen=self._maxlen)
            logger.warning("Moved message %s to DLQ: %s", message_id, reason)
        except Exception:
            logger.exception("Failed to move message %s to DLQ", message_id)
            raise
