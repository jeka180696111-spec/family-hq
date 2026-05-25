"""Shared memory operations for Family HQ agents.

Provides:
    SharedMemory – stateless helper that wraps a SQLAlchemy async engine.

Public methods
--------------
get_recent_messages(chat_id, limit)   -> list[dict]
get_user_rules(agent_id)              -> list[dict]
get_agent_setting(agent_id, key, default) -> str
set_agent_setting(agent_id, key, value)   -> None
save_message(message_data)            -> int   (new message id)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from .models import AgentSetting, Message, UserRule

log = structlog.get_logger(__name__)


class SharedMemory:
    """Async helper for shared cross-agent database reads and writes."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def get_recent_messages(
        self, chat_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return the *limit* most-recent messages for *chat_id*, newest first."""
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            result = await session.execute(
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(desc(Message.date))
                .limit(limit)
            )
            rows = result.scalars().all()

        messages = [_message_to_dict(row) for row in rows]
        log.debug(
            "memory.get_recent_messages",
            chat_id=chat_id,
            limit=limit,
            returned=len(messages),
        )
        return messages

    async def save_message(self, message_data: dict[str, Any]) -> int:
        """Insert a new message row and return its auto-assigned id.

        *message_data* keys mirror the ``messages`` table columns.
        ``date`` defaults to the current UTC ISO timestamp when omitted.
        """
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            async with session.begin():
                msg = Message(
                    tg_message_id=message_data["tg_message_id"],
                    chat_id=message_data["chat_id"],
                    user_id=message_data.get("user_id"),
                    agent_id=message_data.get("agent_id"),
                    text=message_data.get("text"),
                    has_media=int(message_data.get("has_media", 0)),
                    media_path=message_data.get("media_path"),
                    date=message_data.get(
                        "date", datetime.now(timezone.utc).isoformat()
                    ),
                    parsed_actions=message_data.get("parsed_actions"),
                )
                session.add(msg)
            await session.refresh(msg)
            msg_id: int = msg.id  # type: ignore[assignment]

        log.info("memory.save_message", message_id=msg_id, chat_id=message_data["chat_id"])
        return msg_id

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    async def get_user_rules(self, agent_id: str) -> list[dict[str, Any]]:
        """Return all active rules that belong to *agent_id*."""
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            result = await session.execute(
                select(UserRule).where(
                    UserRule.agent_id == agent_id,
                    UserRule.active == 1,
                )
            )
            rows = result.scalars().all()

        rules = [_rule_to_dict(row) for row in rows]
        log.debug("memory.get_user_rules", agent_id=agent_id, returned=len(rules))
        return rules

    # ------------------------------------------------------------------
    # Agent settings
    # ------------------------------------------------------------------

    async def get_agent_setting(
        self, agent_id: str, key: str, default: str = ""
    ) -> str:
        """Return the stored value for ``(agent_id, key)``, or *default*."""
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            result = await session.execute(
                select(AgentSetting).where(
                    AgentSetting.agent_id == agent_id,
                    AgentSetting.key == key,
                )
            )
            row = result.scalar_one_or_none()

        value: str = row.value if row is not None else default
        log.debug(
            "memory.get_agent_setting",
            agent_id=agent_id,
            key=key,
            found=row is not None,
        )
        return value

    async def set_agent_setting(
        self, agent_id: str, key: str, value: str
    ) -> None:
        """Upsert a ``(agent_id, key) → value`` setting row."""
        now_iso: str = datetime.now(timezone.utc).isoformat()
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            async with session.begin():
                stmt = sqlite_insert(AgentSetting).values(
                    agent_id=agent_id,
                    key=key,
                    value=value,
                    updated_at=now_iso,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["agent_id", "key"],
                    set_={"value": value, "updated_at": now_iso},
                )
                await session.execute(stmt)

        log.info("memory.set_agent_setting", agent_id=agent_id, key=key)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _message_to_dict(row: Message) -> dict[str, Any]:
    return {
        "id": row.id,
        "tg_message_id": row.tg_message_id,
        "chat_id": row.chat_id,
        "user_id": row.user_id,
        "agent_id": row.agent_id,
        "text": row.text,
        "has_media": row.has_media,
        "media_path": row.media_path,
        "date": row.date,
        "parsed_actions": row.parsed_actions,
    }


def _rule_to_dict(row: UserRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "rule_type": row.rule_type,
        "pattern": row.pattern,
        "action": row.action,
        "created_at": row.created_at,
        "created_by": row.created_by,
        "active": row.active,
    }
