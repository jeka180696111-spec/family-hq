from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.agents.calendar import CalendarAgent
    from src.integrations.telegram_bots import BotManager

log = structlog.get_logger()


async def check_upcoming_reminders(
    calendar_agent: "CalendarAgent",
    bot_manager: "BotManager",
    chat_id: int,
) -> None:
    """
    Check for events happening today or tomorrow.
    Send reminders for any that haven't been announced yet.
    Scheduled every hour.
    """
    if not calendar_agent._calendar:
        return

    try:
        from datetime import timedelta

        from src.utils.time import now_kyiv

        now = now_kyiv()
        events = await calendar_agent._calendar.list_upcoming(days=2)

        for event in events:
            delta = event.start - now
            hours_until = delta.total_seconds() / 3600

            # Remind at ~24h before and ~1h before
            if 23 <= hours_until <= 25:
                await bot_manager.send_message(
                    "calendar",
                    chat_id,
                    f"📅 Напоминание: завтра — «{event.title}»\n"
                    f"⏰ {event.start.strftime('%d.%m %H:%M')}",
                )
            elif 0.5 <= hours_until <= 1.5:
                await bot_manager.send_message(
                    "calendar",
                    chat_id,
                    f"📅 ⏰ Через час: «{event.title}»",
                )

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
        hours=1,
        args=[calendar_agent, bot_manager, chat_id],
        id="calendar_reminders",
        replace_existing=True,
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
