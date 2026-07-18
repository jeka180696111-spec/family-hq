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

        # Butler + любое действие от другого агента → подтверждение
        if agent_id == "butler" and bot_manager is not None:
            handled = await _maybe_confirm_butler_action(
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


async def _maybe_confirm_butler_action(
    line: str, origin_agent: str, bot_manager: Any, chat_id: int,
) -> bool:
    """ЛЮБАЯ директива Butler от другого агента → подтверждение.
    Если в директиве есть «запусти сцену «X»» — детальное подтверждение
    (показания датчика + имя сцены). Иначе — обобщённое.
    """
    import re
    # Показания датчика (общий блок для обоих режимов)
    sensor_line = ""
    try:
        from src.config import get_settings
        from src.integrations.tuya import TuyaClient
        settings = get_settings()
        tuya = TuyaClient.from_settings(settings)
        if tuya:
            sensor_name = settings.baby_room_sensor_name or "детская"
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

    origin_label = {
        "nanny": "Няня", "news": "Дозорный", "calendar": "Ежедневник",
        "cook": "Гурман", "health": "Айболит",
        "devops": "Прораб", "navigator": "Штурман",
    }.get(origin_agent, origin_agent)

    # === Режим 1: запуск конкретной сцены ===
    if "запусти сцен" in line.lower():
        m = re.search(r"«([^»]+)»", line)
        if m:
            scene_query = m.group(1)
            return await _confirm_scene(
                scene_query, origin_agent, origin_label,
                sensor_line, bot_manager, chat_id,
            )

    # === Режим 2: произвольная команда (свет, кондер, увлажнитель...) ===
    # Убираем префикс «Дворецкий, » чтобы показать чистую команду
    clean = re.sub(r"^дворецкий[,!?.\s]+", "", line, flags=re.IGNORECASE).strip()
    # Убираем финальную точку/восклицательный
    clean = clean.rstrip(".!")

    from src.orchestrator.butler_confirm import add_pending_command
    sid = add_pending_command(line, origin_agent)

    text_lines = []
    if sensor_line:
        text_lines.append(f"🏠 В детской сейчас: {sensor_line}")
    text_lines.append(f"{origin_label} просит: <b>{clean}</b>")
    text_lines.append("Выполнить?")
    text = "\n".join(text_lines)

    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Да", "callback_data": f"butler.cmd|yes|{sid}"},
            {"text": "❌ Нет", "callback_data": f"butler.cmd|no|{sid}"},
        ]]
    }
    await bot_manager.send_message(
        agent_id="butler", chat_id=chat_id, text=text,
        parse_mode="HTML", reply_markup=reply_markup,
    )
    log.info("butler_command_confirm_posted", directive=clean[:80], sid=sid)
    return True


async def _confirm_scene(
    scene_query: str, origin_agent: str, origin_label: str,
    sensor_line: str, bot_manager: Any, chat_id: int,
) -> bool:
    """Подтверждение для конкретной сцены Tuya."""
    try:
        from src.config import get_settings
        from src.integrations.tuya import TuyaClient
        tuya = TuyaClient.from_settings(get_settings())
        if not tuya:
            return False

        match = await tuya.find_scene(scene_query)
        if not match or match.get("ambiguous"):
            await bot_manager.send_message(
                agent_id="butler", chat_id=chat_id,
                text=f"🏠 «{scene_query}» — сцена не найдена, не выполняю.",
            )
            return True

        from src.orchestrator.butler_confirm import add_pending
        sid = add_pending(match["id"], match["name"], origin_agent)

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
        log.exception("butler_confirm_failed", query=scene_query[:80])
        return False
