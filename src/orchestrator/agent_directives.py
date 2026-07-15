"""Универсальный обработчик директив «Агент X, ...» в проактивных
сообщениях (scheduler-джобы).

Проблема: dispatch_chain в main.py работает только для сообщений
которые идут через диспетчер (от юзера). Scheduler-джобы (morning_brief,
sleep_reactor, baby_room_monitor и т.д.) шлют напрямую через bot_manager
и минуют цепочку → если такой джоб сгенерил текст с обращением
к другому агенту, тот его не увидит.

Этот модуль парсит текст, находит строки-обращения к агентам
и вызывает их handle() чтобы они реально ответили.
"""
from __future__ import annotations
import re
from typing import Any
import structlog

log = structlog.get_logger()

# Имена агентов и все возможные обращения (падежи).
# Синхронизировано с _AGENT_NAME_PATTERNS в main.py.
_AGENT_ALIASES: dict[str, list[str]] = {
    "butler": ["дворецкий", "дворецкому", "дворецкого"],
    "nanny": ["няня", "няне", "няню"],
    "news": ["дозорный", "дозорному", "дозорного"],
    "calendar": ["ежедневник", "ежедневнику", "календарь"],
    "cook": ["гурман", "гурману", "гурмана"],
    "health": ["айболит", "айболиту"],
    "devops": ["прораб", "прорабу", "прораба"],
    "navigator": ["штурман", "штурману", "штурмана"],
}


def extract_directives(text: str) -> list[tuple[str, str]]:
    """Вернуть список пар (agent_id, полная строка-директива).

    Ищет строки в тексте начинающиеся с имени агента и запятой/пробела.
    """
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        for agent_id, names in _AGENT_ALIASES.items():
            for name in names:
                if low.startswith(name + ",") or low.startswith(name + " "):
                    out.append((agent_id, line))
                    break
            else:
                continue
            break
    return out


async def execute_directives(
    text: str,
    agents: dict[str, Any],
    memory: Any,
    chat_id: int,
    origin_agent: str | None = None,
) -> None:
    """Парсит text, для каждой директивы вызывает handle() адресата.

    Каждый агент отвечает в чат сам через свой bot; фактически то же
    что при dispatch_chain, но без диспетчера — прямой вызов.
    """
    directives = extract_directives(text)
    if not directives:
        return
    from src.orchestrator.conversation import ConversationContext
    context = ConversationContext(memory, chat_id)
    for agent_id, line in directives:
        if agent_id == origin_agent:
            continue  # не звать самого себя
        agent = agents.get(agent_id)
        if agent is None:
            log.warning("directive_target_missing", agent_id=agent_id)
            continue
        try:
            log.info(
                "executing_agent_directive",
                target=agent_id, origin=origin_agent,
                line_preview=line[:80],
            )
            await agent.handle(
                message_text=line,
                sender_name=f"[{origin_agent or 'scheduler'}]",
                context=context,
            )
        except Exception:
            log.exception(
                "directive_execution_failed",
                target=agent_id, line=line[:80],
            )
