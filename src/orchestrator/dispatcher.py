from __future__ import annotations
import json
from typing import Any
from pydantic import BaseModel
import structlog

from src.integrations.claude_client import ClaudeClient
from src.prompts.dispatcher import DISPATCHER_SYSTEM

log = structlog.get_logger()

class AgentTask(BaseModel):
    agent_id: str
    priority: str  # "critical" | "high" | "normal" | "low"
    reason: str

class DispatchResult(BaseModel):
    tasks: list[AgentTask]
    is_critical: bool = False
    is_settings_command: bool = False

class Dispatcher:
    """
    Determines which agents should respond to a message.
    Uses Claude Haiku for fast classification.
    """

    def __init__(self, claude_client: ClaudeClient, model: str) -> None:
        self._claude = claude_client
        self._model = model

    async def dispatch(
        self,
        message_text: str,
        sender_name: str,
        active_agent_ids: list[str],
        recent_context: list[dict[str, Any]] | None = None,
    ) -> DispatchResult:
        """
        Classify a message and return which agents should respond.
        Falls back to ["nanny"] if classification fails.
        """
        messages = []
        if recent_context:
            ctx_str = "\n".join(
                f"{m.get('sender', '?')}: {m.get('text', '')[:100]}"
                for m in recent_context[-5:]
            )
            messages.append({
                "role": "user",
                "content": f"Контекст последних сообщений:\n{ctx_str}\n\nНовое сообщение от {sender_name}:\n{message_text}"
            })
        else:
            messages.append({
                "role": "user",
                "content": f"Сообщение от {sender_name}:\n{message_text}"
            })

        try:
            response = await self._claude.complete(
                model=self._model,
                system=DISPATCHER_SYSTEM,
                messages=messages,
                max_tokens=512,
            )
            data = json.loads(response)
            # Filter to only active agents
            tasks = [
                AgentTask(**a) for a in data.get("agents", [])
                if a.get("id") in active_agent_ids
            ]
            if not tasks:
                tasks = [AgentTask(agent_id="nanny", priority="normal", reason="fallback")]
            return DispatchResult(
                tasks=tasks,
                is_critical=data.get("is_critical", False),
                is_settings_command=data.get("is_settings_command", False),
            )
        except Exception:
            log.exception("dispatch_failed", message=message_text[:50])
            return DispatchResult(
                tasks=[AgentTask(agent_id="nanny", priority="normal", reason="error_fallback")]
            )
