from __future__ import annotations
import json
import re
from typing import Any
from pydantic import BaseModel
import structlog

from src.integrations.claude_client import ClaudeClient
from src.prompts.dispatcher import DISPATCHER_SYSTEM

log = structlog.get_logger()

EXTERNAL_AGENT = "EXTERNAL_AGENT"


def _extract_json(text: str) -> str:
    """Strip markdown code fences and return the first {...} block."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


class AgentTask(BaseModel):
    agent_id: str
    priority: str  # "critical" | "high" | "normal" | "low"
    reason: str


class DispatchResult(BaseModel):
    tasks: list[AgentTask]
    is_critical: bool = False
    is_settings_command: bool = False
    intent: str = ""
    is_external: bool = False


class Dispatcher:
    """
    Determines which agents should respond to a message.
    Uses Claude Haiku for fast classification.
    Finance intent returns is_external=True — Фінн handles it autonomously.
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
        Returns is_external=True for finance intent (Фінн handles it, dispatcher stays silent).
        Falls back to ["nanny"] if classification fails.
        """
        def _label(m: dict) -> str:
            aid = m.get("agent_id")
            if aid:
                return f"[{aid}]"
            uid = m.get("user_id")
            return f"user#{uid}" if uid else "user"

        messages = []
        if recent_context:
            ctx_str = "\n".join(
                f"{_label(m)}: {m.get('text', '')[:150]}"
                for m in recent_context[-6:]
            )
            messages.append({
                "role": "user",
                "content": (
                    f"Контекст последних сообщений (агенты в [скобках]):\n{ctx_str}\n\n"
                    f"Новое сообщение от {sender_name}:\n{message_text}"
                )
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
            data = json.loads(_extract_json(response))
            intent = data.get("intent", "")

            # Finance → external agent (Фінн), dispatcher stays silent
            if intent == "finance" or not data.get("agents"):
                if intent == "finance":
                    log.info("dispatch_external_finn", message=message_text[:50])
                    return DispatchResult(
                        tasks=[],
                        is_critical=False,
                        is_settings_command=False,
                        intent="finance",
                        is_external=True,
                    )

            # Filter to only active agents (JSON uses "id", model uses "agent_id")
            tasks = [
                AgentTask(
                    agent_id=a["id"],
                    priority=a.get("priority", "normal"),
                    reason=a.get("reason", ""),
                )
                for a in data.get("agents", [])
                if a.get("id") in active_agent_ids
            ]
            if not tasks:
                tasks = [AgentTask(agent_id="nanny", priority="normal", reason="fallback")]
            return DispatchResult(
                tasks=tasks,
                is_critical=data.get("is_critical", False),
                is_settings_command=data.get("is_settings_command", False),
                intent=intent,
                is_external=False,
            )
        except Exception:
            log.exception("dispatch_failed", message=message_text[:50])
            return DispatchResult(
                tasks=[AgentTask(agent_id="nanny", priority="normal", reason="error_fallback")]
            )
