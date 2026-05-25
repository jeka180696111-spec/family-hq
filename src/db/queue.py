"""Message queue for Family HQ AI offline mode.

Provides:
    MessageQueue – async wrapper around the ``pending_queue`` table.

Public methods
--------------
enqueue(message_id, intended_agents)  -> None
drain()                               -> list[dict]  (unprocessed items)
mark_processed(queue_id)              -> None
status()                              -> dict  {count: int, oldest_at: str | None}
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import structlog
from sqlalchemy import asc, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from .models import PendingQueue

log = structlog.get_logger(__name__)


class MessageQueue:
    """Async queue backed by the ``pending_queue`` SQLite table."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    async def enqueue(
        self, message_id: int | None, intended_agents: list[str]
    ) -> None:
        """Add a new item to the queue.

        *message_id* may be ``None`` for messages that were never persisted
        (e.g. offline drops before the messages table write succeeded).
        *intended_agents* is serialised to JSON for storage.
        """
        now_iso: str = datetime.now(timezone.utc).isoformat()
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            async with session.begin():
                session.add(
                    PendingQueue(
                        message_id=message_id,
                        intended_agents=json.dumps(intended_agents),
                        enqueued_at=now_iso,
                        processed_at=None,
                    )
                )
        log.info(
            "queue.enqueued",
            message_id=message_id,
            agents=intended_agents,
        )

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    async def drain(self) -> list[dict[str, Any]]:
        """Return all unprocessed queue items (oldest first), without marking them.

        Callers should call :meth:`mark_processed` for each item they
        successfully handle.
        """
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            result = await session.execute(
                select(PendingQueue)
                .where(PendingQueue.processed_at.is_(None))
                .order_by(asc(PendingQueue.enqueued_at))
            )
            rows = result.scalars().all()

        items = [_queue_row_to_dict(row) for row in rows]
        log.debug("queue.drain", returned=len(items))
        return items

    # ------------------------------------------------------------------
    # Mark processed
    # ------------------------------------------------------------------

    async def mark_processed(self, queue_id: int) -> None:
        """Stamp ``processed_at`` on the given queue row."""
        now_iso: str = datetime.now(timezone.utc).isoformat()
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            async with session.begin():
                row = await session.get(PendingQueue, queue_id)
                if row is None:
                    log.warning("queue.mark_processed.not_found", queue_id=queue_id)
                    return
                row.processed_at = now_iso  # type: ignore[assignment]
        log.info("queue.mark_processed", queue_id=queue_id)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        """Return a summary dict with ``count`` and ``oldest_at``.

        ``oldest_at`` is ``None`` when the queue is empty.
        """
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            count_result = await session.execute(
                select(func.count()).select_from(PendingQueue).where(
                    PendingQueue.processed_at.is_(None)
                )
            )
            count: int = count_result.scalar_one()

            oldest_at: str | None = None
            if count > 0:
                oldest_result = await session.execute(
                    select(PendingQueue.enqueued_at)
                    .where(PendingQueue.processed_at.is_(None))
                    .order_by(asc(PendingQueue.enqueued_at))
                    .limit(1)
                )
                oldest_at = oldest_result.scalar_one_or_none()

        result: dict[str, Any] = {"count": count, "oldest_at": oldest_at}
        log.debug("queue.status", **result)
        return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _queue_row_to_dict(row: PendingQueue) -> dict[str, Any]:
    try:
        agents: list[str] = json.loads(row.intended_agents)
    except (json.JSONDecodeError, TypeError):
        agents = [row.intended_agents]  # type: ignore[list-item]

    return {
        "id": row.id,
        "message_id": row.message_id,
        "intended_agents": agents,
        "enqueued_at": row.enqueued_at,
        "processed_at": row.processed_at,
    }
