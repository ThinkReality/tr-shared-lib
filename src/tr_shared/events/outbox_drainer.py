"""Outbox drainer — scans {schema}.undelivered_events and publishes to Redis Stream.

Shipped as a pure async function + a Celery task factory. Each service
wires it into its own beat schedule at the configured interval.

Retry semantics:
- On publish success: row's ``published_at`` is set.
- On publish failure: ``retry_count`` is incremented and ``next_retry_at``
  is advanced by exponential backoff (``RetryPolicy``).
- After ``max_retries`` failures: row is marked ``dead_letter=TRUE`` and
  the caller-supplied ``on_dead_letter`` callback fires. Events are NEVER
  silently discarded.

Default beat schedule is **30 seconds** — tradeoff between "pay one DB
SELECT every 30s" and "recover within 30s after a Redis hiccup". Each
service can override in its own ``celery_app.py`` beat_schedule.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tr_shared.events.producer import EventProducer
from tr_shared.events.retry_policy import RetryPolicy

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

DEFAULT_DRAINER_INTERVAL_SECONDS: float = 30.0


DeadLetterCallback = Callable[[dict[str, Any]], Awaitable[None]] | None


async def _default_dead_letter_callback(row: dict[str, Any]) -> None:
    """Default DLQ callback: structured-log the event so ops can alert on it."""
    logger.error(
        "event_dead_letter",
        extra={
            "event_id": str(row.get("id")),
            "event_type": row.get("event_type"),
            "tenant_id": str(row.get("tenant_id")),
            "retry_count": row.get("retry_count"),
            "last_error": row.get("last_error"),
            "metric": "event_dead_letter",
        },
    )


async def drain_outbox(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    producer: EventProducer,
    schema: str,
    table_name: str = "undelivered_events",
    batch_size: int = 100,
    retry_policy: RetryPolicy | None = None,
    on_dead_letter: DeadLetterCallback = None,
) -> dict[str, int]:
    """Drain one batch of due outbox rows. Returns {published, retried, dead_lettered}.

    Each row is processed in its own short transaction so a poison row
    cannot block others. The outer SELECT uses ``FOR UPDATE SKIP LOCKED``
    so multiple drainer workers do not fight for the same rows.
    """
    policy = retry_policy or RetryPolicy(max_retries=10)
    dlq_cb = on_dead_letter or _default_dead_letter_callback

    published = 0
    retried = 0
    dead_lettered = 0

    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    f"""
                    SELECT id, event_type, tenant_id, actor_id, data, metadata,
                           retry_count
                    FROM {schema}.{table_name}
                    WHERE published_at IS NULL
                      AND dead_letter = FALSE
                      AND next_retry_at <= NOW()
                    ORDER BY next_retry_at ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                    """,
                ),
                {"limit": batch_size},
            )
            rows = [dict(row) for row in result.mappings().all()]

        for row in rows:
            event_id: UUID = row["id"]
            data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
            metadata = (
                row["metadata"]
                if isinstance(row["metadata"], dict)
                else json.loads(row["metadata"] or "{}")
            )
            correlation_id = metadata.get("correlation_id")

            try:
                await producer.publish(
                    event_type=row["event_type"],
                    tenant_id=str(row["tenant_id"]),
                    data=data,
                    actor_id=str(row["actor_id"]) if row["actor_id"] else None,
                    metadata=metadata,
                    correlation_id=correlation_id,
                )
                async with session_factory() as s2, s2.begin():
                    await s2.execute(
                        text(
                            f"UPDATE {schema}.{table_name} "
                            "SET published_at = NOW() WHERE id = :id",
                        ),
                        {"id": str(event_id)},
                    )
                published += 1
            except Exception as exc:  # noqa: BLE001 — drainer never raises per-row
                next_count = row["retry_count"] + 1
                if next_count >= policy.max_retries:
                    async with session_factory() as s2, s2.begin():
                        await s2.execute(
                            text(
                                f"UPDATE {schema}.{table_name} "
                                "SET dead_letter = TRUE, retry_count = :n, "
                                "last_error = :err WHERE id = :id",
                            ),
                            {"id": str(event_id), "n": next_count, "err": str(exc)[:500]},
                        )
                    try:
                        await dlq_cb({**row, "retry_count": next_count, "last_error": str(exc)})
                    except Exception:  # noqa: BLE001
                        logger.exception("dlq callback failed for event %s", event_id)
                    dead_lettered += 1
                else:
                    delay_seconds = policy.delay_for(next_count)
                    next_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                    async with session_factory() as s2, s2.begin():
                        await s2.execute(
                            text(
                                f"UPDATE {schema}.{table_name} "
                                "SET retry_count = :n, next_retry_at = :at, "
                                "last_error = :err WHERE id = :id",
                            ),
                            {
                                "id": str(event_id),
                                "n": next_count,
                                "at": next_at,
                                "err": str(exc)[:500],
                            },
                        )
                    retried += 1

    return {"published": published, "retried": retried, "dead_lettered": dead_lettered}


def create_outbox_drainer_task(
    celery_app: Any,
    *,
    task_name: str,
    schema: str,
    session_factory_getter: Callable[[], async_sessionmaker[AsyncSession]],
    producer_getter: Callable[[], EventProducer],
    table_name: str = "undelivered_events",
    batch_size: int = 100,
    retry_policy: RetryPolicy | None = None,
    on_dead_letter: DeadLetterCallback = None,
) -> Any:
    """Register a Celery task that calls ``drain_outbox`` once.

    Getters are used (not direct instances) because Celery workers fork
    and each worker owns its own event loop / engine / redis client —
    getters let services defer construction to task-execution time.

    Returns the registered Celery task so callers can reference it in
    ``beat_schedule``.
    """
    import asyncio

    @celery_app.task(name=task_name, bind=False)
    def _task() -> dict[str, int]:
        return asyncio.run(
            drain_outbox(
                session_factory=session_factory_getter(),
                producer=producer_getter(),
                schema=schema,
                table_name=table_name,
                batch_size=batch_size,
                retry_policy=retry_policy,
                on_dead_letter=on_dead_letter,
            ),
        )

    return _task


__all__ = [
    "DEFAULT_DRAINER_INTERVAL_SECONDS",
    "create_outbox_drainer_task",
    "drain_outbox",
]
