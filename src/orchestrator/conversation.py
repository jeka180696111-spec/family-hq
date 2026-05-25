from __future__ import annotations
from typing import Any
import structlog

from src.db.memory import SharedMemory

log = structlog.get_logger()

class ConversationContext:
    """
    Manages conversation context for agents.
    Keeps last N messages per chat for context window.
    """

    DEFAULT_CONTEXT_SIZE = 20

    def __init__(self, memory: SharedMemory, chat_id: int) -> None:
        self._memory = memory
        self._chat_id = chat_id

    async def get_recent(self, limit: int = DEFAULT_CONTEXT_SIZE) -> list[dict[str, Any]]:
        """Get recent messages for context."""
        return await self._memory.get_recent_messages(self._chat_id, limit)

    async def save_message(
        self,
        tg_message_id: int,
        user_id: int | None,
        agent_id: str | None,
        text: str,
        has_media: bool = False,
        parsed_actions: list[dict] | None = None,
    ) -> int:
        """Save a message to shared memory. Returns DB id."""
        import json
        from src.utils.time import iso_now
        return await self._memory.save_message({
            "tg_message_id": tg_message_id,
            "chat_id": self._chat_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "text": text,
            "has_media": int(has_media),
            "date": iso_now(),
            "parsed_actions": json.dumps(parsed_actions) if parsed_actions else None,
        })

    def format_for_agent(self, messages: list[dict[str, Any]], max_messages: int = 10) -> list[dict]:
        """
        Format recent messages as Claude conversation history.
        Returns list of {"role": "user"|"assistant", "content": "..."} dicts.
        """
        result = []
        for msg in messages[-max_messages:]:
            if msg.get("agent_id"):
                role = "assistant"
                content = f"[{msg['agent_id']}]: {msg.get('text', '')}"
            else:
                role = "user"
                content = msg.get("text", "")
            if content:
                result.append({"role": role, "content": content})
        return result
