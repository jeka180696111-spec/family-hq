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


# Direct-address routing — works even when the LLM dispatcher is down.
# Key: any of these tokens at the start of the message (case-insensitive,
# optional comma/colon/space after) routes the message to the value agent_id.
_ADDRESS_PREFIX_TO_AGENT = {
    "прораб":        "devops",
    "прорабе":       "devops",
    "прораба":       "devops",
    "няня":          "nanny",
    "няне":          "nanny",
    "нянь":          "nanny",
    "гурман":        "cook",
    "гурмане":       "cook",
    "повар":         "cook",
    "дозорный":      "news",
    "дозорному":     "news",
    "дозорная":      "news",
    "айболит":       "health",
    "айболите":      "health",
    "доктор":        "health",
    "штурман":       "navigator",
    "штурмане":      "navigator",
    "навигатор":     "navigator",
    "ежедневник":    "calendar",
    "календарь":     "calendar",
}


def _direct_address_agent(message_text: str) -> str | None:
    """If the message starts with an agent's nickname (Прораб, Няня…),
    return the corresponding agent_id. Beats the LLM dispatcher on
    speed, cost, and correctness — and works when AI is down."""
    if not message_text:
        return None
    head = message_text.lstrip().lower()
    # Strip leading @ for telegram @mentions
    head = head.lstrip("@")
    for prefix, agent_id in _ADDRESS_PREFIX_TO_AGENT.items():
        if head.startswith(prefix):
            # Must be followed by space / punctuation / end-of-string —
            # avoid matching "прорабе" inside «прорабенок» or similar.
            tail = head[len(prefix):]
            if not tail or tail[0] in " ,.:;!?-—\n":
                return agent_id
    return None


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
        # Direct address shortcut — bypass LLM entirely when the user
        # explicitly addresses an agent ("Прораб, ..." / "Няня, ..."):
        addressed = _direct_address_agent(message_text)
        if addressed and addressed in active_agent_ids:
            log.info("dispatch_direct_address", agent=addressed, message=message_text[:50])
            return DispatchResult(
                tasks=[AgentTask(
                    agent_id=addressed, priority="normal",
                    reason="direct_address",
                )],
                is_critical=False,
                is_settings_command=False,
                intent="direct",
                is_external=False,
            )

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
