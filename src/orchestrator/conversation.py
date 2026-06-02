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

    def format_for_agent(
        self,
        messages: list[dict[str, Any]],
        max_messages: int = 10,
        self_agent_id: str | None = None,
    ) -> list[dict]:
        """
        Format recent messages as Claude conversation history.

        From the viewpoint of *self_agent_id*:
        - messages this agent posted earlier → role 'assistant' (his own words)
        - messages from other agents → role 'user' with '[agent_id]:' prefix
          so he knows whose words they are and doesn't echo them as his own
        - human messages → role 'user'

        If self_agent_id is None (legacy), all agent messages get 'assistant'.
        """
        result: list[dict] = []
        for msg in messages[-max_messages:]:
            aid = msg.get("agent_id")
            text = msg.get("text", "")
            if not text:
                continue
            if aid:
                if self_agent_id and aid == self_agent_id:
                    result.append({"role": "assistant", "content": text})
                else:
                    result.append({"role": "user", "content": f"[{aid}]: {text}"})
            else:
                result.append({"role": "user", "content": text})

        # Anthropic API requires the first message to be 'user'. If the recent
        # window starts with an 'assistant' message (rare edge case), drop it.
        while result and result[0]["role"] == "assistant":
            result.pop(0)

        # Also collapse consecutive same-role messages by joining content
        merged: list[dict] = []
        for m in result:
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"] = merged[-1]["content"] + "\n" + m["content"]
            else:
                merged.append(m)
        return merged
