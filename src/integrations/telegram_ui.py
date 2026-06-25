"""Telegram UI helpers: inline keyboards, callbacks, edit-in-place, charts.

UI_MODE env flag:
  - 'enhanced' (default): inline keyboards, edit-in-place, photo cards
  - 'classic': plain text messages, no buttons (rollback)
"""
from __future__ import annotations

import json
from typing import Any

import structlog

log = structlog.get_logger()


def ui_mode() -> str:
    from src.config import get_settings
    return (getattr(get_settings(), "ui_mode", "enhanced") or "enhanced").lower()


def is_enhanced() -> bool:
    return ui_mode() == "enhanced"


# ─── Keyboard factories ──────────────────────────────────────────────

def kb_nanny_quick_actions() -> list[list[dict]]:
    """4 quick actions Няня offers after recording an event."""
    return [
        [
            {"text": "🌅 Проснулся", "callback_data": "nanny.event|wake"},
            {"text": "🍼 Покормил",  "callback_data": "nanny.event|feed"},
        ],
        [
            {"text": "💧 Подгузник", "callback_data": "nanny.event|diaper"},
            {"text": "🌡️ Симптом",  "callback_data": "nanny.event|symptom"},
        ],
    ]


def kb_alert_status() -> list[list[dict]]:
    """Family check-in buttons under air alert."""
    return [
        [{"text": "🛡️ Я в укрытии", "callback_data": "alert.checkin|shelter"}],
        [{"text": "🏠 Дома, в порядке", "callback_data": "alert.checkin|home_ok"}],
        [{"text": "🚗 Не дома", "callback_data": "alert.checkin|away"}],
    ]


def kb_reminder(reminder_id: str | int) -> list[list[dict]]:
    return [[
        {"text": "✅ Сделал", "callback_data": f"rem.done|{reminder_id}"},
        {"text": "⏰ Отложить 1ч", "callback_data": f"rem.snooze|{reminder_id}|60"},
        {"text": "❌ Отмена", "callback_data": f"rem.cancel|{reminder_id}"},
    ]]


def kb_confirm(yes_action: str, no_action: str, yes_text: str = "✅ Да", no_text: str = "❌ Отмена") -> list[list[dict]]:
    return [[
        {"text": yes_text, "callback_data": yes_action},
        {"text": no_text, "callback_data": no_action},
    ]]


def kb_automation_rule(rule_name: str) -> list[list[dict]]:
    """Under each rule listing: pause/delete buttons."""
    return [[
        {"text": "⏸ Пауза", "callback_data": f"auto.toggle|{rule_name}|off"},
        {"text": "🗑 Удалить", "callback_data": f"auto.delete|{rule_name}"},
    ]]


def to_telegram_markup(rows: list[list[dict]]) -> dict:
    """Convert factory output to Telegram inline_keyboard JSON."""
    return {"inline_keyboard": rows}


# ─── Bot menu commands (set once at startup) ─────────────────────────

BOT_MENU_COMMANDS = {
    "nanny": [
        {"command": "wake", "description": "🌅 Проснулся"},
        {"command": "feed", "description": "🍼 Кормление"},
        {"command": "sleep", "description": "😴 Уснул"},
        {"command": "diaper", "description": "💧 Подгузник"},
        {"command": "poop", "description": "💩 Покакал"},
        {"command": "walk", "description": "🚶 Прогулка"},
        {"command": "symptom", "description": "🌡 Симптом / температура"},
        {"command": "weight", "description": "⚖️ Записать вес/рост"},
        {"command": "milestone", "description": "⭐ Новое достижение"},
        {"command": "sleepcoach", "description": "📊 Анализ сна за 14д"},
        {"command": "when_sleep", "description": "🕐 Когда укладывать / будить"},
        {"command": "wake_plan", "description": "🌞 План на бодрствование"},
        {"command": "night", "description": "🌙 Чья очередь дежурить"},
        {"command": "handoff", "description": "📋 Сводка для бабушки"},
    ],
    "news": [
        {"command": "news", "description": "📰 Последние новости"},
        {"command": "alerts", "description": "🚨 Тревоги за сутки"},
        {"command": "power", "description": "⚡ Отключения света"},
        {"command": "weather", "description": "🌤 Погода"},
        {"command": "digest", "description": "📰 Утренний дайджест"},
        {"command": "channels", "description": "📡 Каналы мониторинга"},
    ],
    "calendar": [
        {"command": "today", "description": "📅 Что на сегодня"},
        {"command": "tomorrow", "description": "📅 Что на завтра"},
        {"command": "week", "description": "📆 На неделю"},
        {"command": "shopping", "description": "🛒 Список покупок"},
        {"command": "buy", "description": "➕ Добавить в покупки"},
        {"command": "add", "description": "➕ Добавить событие"},
    ],
    "cook": [
        {"command": "recipe", "description": "🍳 Идеи на ужин"},
        {"command": "menu", "description": "📅 Меню недели"},
        {"command": "foods", "description": "🥗 Что Матвей пробовал"},
        {"command": "nextfood", "description": "➕ Что следующее ввести"},
        {"command": "allergy", "description": "⚠️ Аллергии / реакции"},
    ],
    "health": [
        {"command": "sleep", "description": "😴 Сон родителей"},
        {"command": "doctor", "description": "🩺 Подготовка к врачу"},
        {"command": "vaccines", "description": "💉 Прививки график"},
        {"command": "percentile", "description": "📊 Перцентили (рост/вес)"},
        {"command": "meds", "description": "💊 Лекарства дома"},
        {"command": "symptoms", "description": "🤒 Симптомы за неделю"},
    ],
    "navigator": [
        {"command": "parcels", "description": "📦 Мои посылки"},
        {"command": "track", "description": "🚚 Отследить ТТН"},
        {"command": "route", "description": "🗺 Построить маршрут"},
        {"command": "traffic", "description": "🚦 Пробки в Одессе"},
    ],
    "devops": [
        {"command": "status", "description": "📊 Статус системы"},
        {"command": "ai", "description": "🤖 Статус ИИ"},
        {"command": "chronicle", "description": "📖 Хроника за неделю"},
        {"command": "notebook", "description": "📋 Блокнот: задачи Прораба"},
        {"command": "devices", "description": "🏠 Умный дом"},
        {"command": "scenes", "description": "🎬 Сцены Tuya (кондер 25, выкл…)"},
        {"command": "battery", "description": "🔋 Сколько света осталось"},
        {"command": "outage", "description": "⚡ Свет дали / нет"},
        {"command": "sensor", "description": "🌡 Темп/влажность в детской"},
        {"command": "cost", "description": "💸 Стоимость API"},
        {"command": "modes", "description": "🌍 Режимы (отпуск/болезнь)"},
        {"command": "rules", "description": "⚙️ Правила автоматизации"},
        {"command": "backup", "description": "💾 Бекап БД"},
        {"command": "profile", "description": "👨‍👩‍👦 Профиль семьи"},
        {"command": "sos", "description": "🆘 Экстренные контакты"},
        {"command": "help", "description": "❓ Помощь"},
    ],
}


async def set_bot_menus(bot_manager: Any) -> None:
    """Push menu commands to each bot via setMyCommands."""
    if not is_enhanced():
        return
    for agent_id, commands in BOT_MENU_COMMANDS.items():
        bot = bot_manager.get(agent_id) if hasattr(bot_manager, "get") else None
        if not bot:
            try:
                bot = bot_manager._bots.get(agent_id)
            except Exception:
                bot = None
        if not bot:
            continue
        try:
            from telegram import BotCommand
            await bot.set_my_commands(commands=[
                BotCommand(c["command"], c["description"][:256]) for c in commands
            ])
            log.info("bot_menu_set", agent=agent_id, count=len(commands))
        except Exception:
            log.exception("bot_menu_set_failed", agent=agent_id)


# ─── Edit-in-place tracking ──────────────────────────────────────────

class StatusMessage:
    """Send an initial 'working...' message, edit it as work progresses, finalize."""

    def __init__(self, bot_manager: Any, agent_id: str, chat_id: int) -> None:
        self._bots = bot_manager
        self._agent_id = agent_id
        self._chat_id = chat_id
        self._message_id: int | None = None

    async def start(self, text: str) -> None:
        if not is_enhanced():
            await self._bots.send_message(agent_id=self._agent_id, chat_id=self._chat_id, text=text)
            return
        msg = await self._bots.send_message(agent_id=self._agent_id, chat_id=self._chat_id, text=text)
        self._message_id = getattr(msg, "message_id", None)

    async def update(self, text: str) -> None:
        if not is_enhanced() or self._message_id is None:
            await self._bots.send_message(agent_id=self._agent_id, chat_id=self._chat_id, text=text)
            return
        bot = self._get_bot()
        if bot is None:
            return
        try:
            await bot.edit_message_text(chat_id=self._chat_id, message_id=self._message_id, text=text, parse_mode="HTML")
        except Exception:
            log.debug("edit_in_place_fallback_to_send")
            await self._bots.send_message(agent_id=self._agent_id, chat_id=self._chat_id, text=text)

    def _get_bot(self):
        try:
            return self._bots._bots.get(self._agent_id)
        except Exception:
            return None


# ─── Chart generation ───────────────────────────────────────────────

def render_sleep_chart(daily_data: list[tuple[str, float]], title: str = "Сон Матвея") -> bytes | None:
    """Generate PNG bytes of a bar chart. Returns None if matplotlib not available."""
    if not is_enhanced():
        return None
    try:
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels = [d[0] for d in daily_data]
        values = [d[1] for d in daily_data]

        fig, ax = plt.subplots(figsize=(7, 3.5))
        bars = ax.bar(labels, values, color="#4a90e2")
        # Highlight max
        if values:
            max_idx = values.index(max(values))
            bars[max_idx].set_color("#2ecc71")
        ax.set_ylabel("Часов")
        ax.set_title(title)
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=110)
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        log.exception("chart_render_failed")
        return None


# ─── Callback dispatcher ────────────────────────────────────────────

async def handle_callback(callback: Any, agents: dict, memory: Any, bot_manager: Any, chat_id: int) -> None:
    """Process inline button presses. Callback data format: 'namespace.action|arg1|arg2'."""
    try:
        data = callback.data or ""
        if "|" not in data:
            return
        action, *args = data.split("|")
        log.info("callback_received", action=action, args=args)

        # Quick nanny event recording
        if action == "nanny.event":
            kind = args[0] if args else ""
            mapping = {
                "wake": ("sleep", "Проснулся"),
                "feed": ("food", "Грудь Л"),
                "diaper": ("diaper", "Мокрый"),
                "symptom": ("symptom", "Уточнить"),
            }
            kind_key, event = mapping.get(kind, ("note", kind))
            nanny = agents.get("nanny")
            if nanny and getattr(nanny, "_sheets", None):
                from src.utils.time import now_kyiv
                sender = getattr(callback.from_user, "first_name", "") or ""
                try:
                    await nanny._sheets.append_baby_diary(
                        kind=kind_key, event=event, time=now_kyiv(),
                        author=sender or "family_hq",
                    )
                    await callback.answer(f"✅ Записал: {event}")
                except Exception as e:
                    await callback.answer(f"❌ {e}", show_alert=True)
            return

        if action == "alert.checkin":
            status = args[0] if args else ""
            sender = getattr(callback.from_user, "first_name", "") or "—"
            mapping = {
                "shelter": "🛡️ в укрытии",
                "home_ok": "🏠 дома, в порядке",
                "away": "🚗 не дома",
            }
            label = mapping.get(status, status)
            await bot_manager.send_message(
                agent_id="news", chat_id=chat_id,
                text=f"📍 <b>{sender}</b>: {label}",
            )
            await callback.answer("Отметил")
            return

        if action == "rem.done":
            await callback.answer("✅ Сделано")
            return
        if action == "rem.snooze":
            mins = int(args[1]) if len(args) > 1 else 60
            await callback.answer(f"⏰ Напомню через {mins} мин")
            return
        if action == "rem.cancel":
            await callback.answer("❌ Отменено")
            return

        if action == "auto.toggle":
            rule_name = args[0]
            new_state = args[1] == "on" if len(args) > 1 else False
            devops = agents.get("devops")
            if devops:
                await devops._automation_toggle(rule_name, new_state)
                await callback.answer(f"Правило {'включено' if new_state else 'выключено'}")
            return

        if action == "auto.delete":
            rule_name = args[0]
            devops = agents.get("devops")
            if devops:
                await devops._automation_delete(rule_name)
                await callback.answer("Удалено")
            return

        await callback.answer()
    except Exception:
        log.exception("callback_handle_failed")
