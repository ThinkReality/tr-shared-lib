"""
Redis buffer for Layer 2 monitoring persistence.

Provides a simple RPUSH/LPOP buffer that the ``PersistenceMiddleware``
writes to and the ``flush_monitoring_buffer`` Celery task reads from.

Key format: ``monitoring:buffer:{service_name}``

Each record is a JSON-serialized dict representing one HTTP request.
A 48-hour TTL acts as a safety net against unbounded growth if the
Celery consumer stops running.

Usage::

    from tr_shared.monitoring.redis_buffer import push_to_buffer, flush_buffer

    # In middleware (async)
    await push_to_buffer(redis_client, "crm-backend", record)

    # In Celery task (sync)
    records = flush_buffer_sync(redis_url, "crm-backend", batch_size=500)
"""

import json
import logging

logger = logging.getLogger(__name__)

BUFFER_KEY_TEMPLATE = "monitoring:buffer:{service_name}"
BUFFER_TTL_SECONDS = 48 * 3600  # 48 hours


def get_buffer_key(service_name: str) -> str:
    """Return the Redis key for a service's monitoring buffer."""
    return BUFFER_KEY_TEMPLATE.format(service_name=service_name)


async def push_to_buffer(
    redis_client,
    service_name: str,
    data: dict,
) -> None:
    """
    RPUSH a JSON-serialized record to the buffer list.

    Fire-and-forget: errors are logged but never raised so the
    middleware never blocks request handling.

    Args:
        redis_client: An ``aioredis``/``redis.asyncio`` client.
        service_name: Service identifier (used in the key).
        data: Request metrics dict to persist.
    """
    key = get_buffer_key(service_name)
    try:
        payload = json.dumps(data, default=str)
        await redis_client.rpush(key, payload)
        # Refresh TTL so the key doesn't expire while actively buffering
        await redis_client.expire(key, BUFFER_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Failed to push monitoring record to Redis: %s", exc)


def flush_buffer_sync(
    redis_client,
    service_name: str,
    batch_size: int = 500,
) -> list[dict]:
    """
    LPOP up to *batch_size* records from the buffer (synchronous).

    Intended for use inside Celery tasks where the event loop is not
    available. Uses a Redis pipeline for efficiency.

    Args:
        redis_client: A synchronous ``redis.Redis`` client.
        service_name: Service identifier.
        batch_size: Maximum records to pop in one call.

    Returns:
        List of parsed dicts (may be shorter than *batch_size*).
    """
    key = get_buffer_key(service_name)
    records: list[dict] = []
    try:
        pipe = redis_client.pipeline()
        for _ in range(batch_size):
            pipe.lpop(key)
        results = pipe.execute()

        for raw in results:
            if raw is None:
                break
            try:
                records.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Skipping malformed monitoring record")
    except Exception as exc:
        logger.error("Failed to flush monitoring buffer: %s", exc)

    return records
