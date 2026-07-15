from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.agents.calendar import CalendarAgent
    from src.integrations.telegram_bots import BotManager

log = structlog.get_logger()


# In-memory dedup: какие напоминания уже отправили в этом процессе.
# Структура: {f"{event_id}|{kind}", ...} — kind ∈ day/hour/15min/now.
_SENT_REMINDERS: set[str] = set()


async def check_upcoming_reminders(
    calendar_agent: "CalendarAgent",
    bot_manager: "BotManager",
    chat_id: int,
) -> None:
    """Check for events happening soon and send timely reminders.

    Тикает каждые 2 минуты. Окна:
    • за 24ч (день перед)  — анонс «завтра»
    • за 60м              — «через час»
    • за 15м              — «через 15 мин»
    • в момент (±90с)      — «сейчас: ...»
    Каждое окно отправляется ОДИН РАЗ на event_id (дедупликация в памяти).
    """
    if not calendar_agent._calendar:
        return

    try:
        from src.utils.time import now_kyiv
        now = now_kyiv()
        events = await calendar_agent._calendar.list_upcoming(days=2)

        for event in events:
            delta_min = (event.start - now).total_seconds() / 60.0
            eid = event.event_id

            # Окна. Полуинтервалы чтоб не дублить.
            windows = [
                (24 * 60 - 5, 24 * 60 + 5, "day",
                 f"📅 Напоминание: завтра — «{event.title}»\n⏰ {event.start.strftime('%d.%m %H:%M')}"),
                (55, 65, "hour",
                 f"📅 ⏰ Через час: «{event.title}» в {event.start.strftime('%H:%M')}"),
                (13, 17, "15min",
                 f"📅 ⏳ Через 15 минут: «{event.title}» в {event.start.strftime('%H:%M')}"),
                (-1.5, 1.5, "now",
                 f"📅 🔔 СЕЙЧАС: «{event.title}»"),
            ]
            for lo, hi, kind, text in windows:
                if lo <= delta_min < hi:
                    key = f"{eid}|{kind}"
                    if key in _SENT_REMINDERS:
                        continue
                    _SENT_REMINDERS.add(key)
                    try:
                        await bot_manager.send_message("calendar", chat_id, text)
                        log.info("reminder_sent", event_title=event.title, kind=kind, delta_min=round(delta_min, 1))
                    except Exception:
                        log.exception("reminder_send_failed", event_title=event.title, kind=kind)

        # Cleanup памяти — забываем напоминания о прошедших событиях
        # (старше суток после события). Иначе set растёт бесконечно.
        if len(_SENT_REMINDERS) > 500:
            from src.utils.time import now_kyiv as _now
            still_relevant = set()
            for e in events:
                eid = e.event_id
                for k in ("day", "hour", "15min", "now"):
                    key = f"{eid}|{k}"
                    if key in _SENT_REMINDERS:
                        still_relevant.add(key)
            _SENT_REMINDERS.clear()
            _SENT_REMINDERS.update(still_relevant)

    except Exception:
        log.exception("reminder_check_failed")


async def cleanup_expired_approvals(memory) -> None:
    """
    Mark expired approval requests as 'expired'.
    Runs every hour.
    """
    from sqlalchemy import update

    from src.db.models import ApprovalRequestModel
    from src.utils.time import iso_now

    async with memory._engine.begin() as conn:
        now = iso_now()
        await conn.execute(
            update(ApprovalRequestModel)
            .where(
                ApprovalRequestModel.status == "pending",
                ApprovalRequestModel.expires_at < now,
            )
            .values(status="expired", resolved_at=now)
        )


def register_reminder_jobs(
    scheduler,
    calendar_agent,
    bot_manager,
    chat_id: int,
    memory,
) -> None:
    """Register reminder and cleanup jobs."""
    scheduler.add_job(
        check_upcoming_reminders,
        "interval",
        minutes=2,
        args=[calendar_agent, bot_manager, chat_id],
        id="calendar_reminders",
        replace_existing=True,
        coalesce=True, max_instances=1,
    )
    scheduler.add_job(
        cleanup_expired_approvals,
        "interval",
        hours=1,
        args=[memory],
        id="cleanup_approvals",
        replace_existing=True,
    )
    log.info("reminder_jobs_registered")
