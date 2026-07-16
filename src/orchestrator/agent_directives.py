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
    bot_manager: Any = None,
) -> None:
    """Парсит text, для каждой директивы вызывает handle() адресата.

    ОСОБЫЙ СЛУЧАЙ для Butler-запусков сцен: если директива содержит
    «запусти сцену «X»» — постим подтверждение с показаниями датчика
    и кнопками Да/Нет вместо мгновенного запуска.
    """
    directives = extract_directives(text)
    if not directives:
        return
    from src.orchestrator.conversation import ConversationContext
    context = ConversationContext(memory, chat_id)
    for agent_id, line in directives:
        if agent_id == origin_agent:
            continue
        agent = agents.get(agent_id)
        if agent is None:
            log.warning("directive_target_missing", agent_id=agent_id)
            continue

        # Butler + запуск сцены → подтверждение вместо мгновенного действия
        if agent_id == "butler" and bot_manager is not None:
            handled = await _maybe_confirm_butler_scene(
                line, origin_agent or "scheduler", bot_manager, chat_id,
            )
            if handled:
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


async def _maybe_confirm_butler_scene(
    line: str, origin_agent: str, bot_manager: Any, chat_id: int,
) -> bool:
    """Если строка содержит «запусти сцену «X»» — постим подтверждение
    с датчиком и кнопками. Возвращает True если обработано.
    """
    import re
    if "запусти сцен" not in line.lower():
        return False
    m = re.search(r"«([^»]+)»", line)
    if not m:
        return False
    scene_query = m.group(1)

    try:
        from src.config import get_settings
        from src.integrations.tuya import TuyaClient
        settings = get_settings()
        tuya = TuyaClient.from_settings(settings)
        if not tuya:
            return False

        # Найти сцену
        match = await tuya.find_scene(scene_query)
        if not match or match.get("ambiguous"):
            await bot_manager.send_message(
                agent_id="butler", chat_id=chat_id,
                text=f"🏠 «{scene_query}» — сцена не найдена, не выполняю.",
            )
            return True

        # Показания датчика
        sensor_name = settings.baby_room_sensor_name or "детская"
        sensor_line = ""
        try:
            sensor = await tuya.read_sensor(sensor_name)
            if isinstance(sensor, dict) and "readings" in sensor:
                r = sensor["readings"]
                parts = []
                if r.get("temperature"):
                    parts.append(f"🌡 {r['temperature']}")
                if r.get("humidity"):
                    parts.append(f"💧 {r['humidity']}")
                if r.get("battery"):
                    parts.append(f"🔋 {r['battery']}")
                sensor_line = " | ".join(parts)
        except Exception:
            pass

        # Регистрируем pending и постим кнопки
        from src.orchestrator.butler_confirm import add_pending
        sid = add_pending(match["id"], match["name"], origin_agent)

        origin_label = {
            "nanny": "Няня", "news": "Дозорный", "calendar": "Ежедневник",
            "cook": "Гурман", "health": "Айболит",
            "devops": "Прораб", "navigator": "Штурман",
        }.get(origin_agent, origin_agent)

        text_lines = []
        if sensor_line:
            text_lines.append(f"🏠 В детской сейчас: {sensor_line}")
        text_lines.append(f"{origin_label} просит запустить сцену «{match['name']}».")
        text_lines.append("Включить?")
        text = "\n".join(text_lines)

        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ Да", "callback_data": f"butler.scene|yes|{sid}"},
                {"text": "❌ Нет", "callback_data": f"butler.scene|no|{sid}"},
            ]]
        }
        await bot_manager.send_message(
            agent_id="butler", chat_id=chat_id, text=text,
            reply_markup=reply_markup,
        )
        log.info("butler_scene_confirm_posted", scene=match["name"], sid=sid)
        return True
    except Exception:
        log.exception("butler_confirm_failed", line=line[:80])
        return False
