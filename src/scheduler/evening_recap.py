"""Evening recap from Прораб — fires at 22:00 Kyiv local.

Кратко: «день прошёл. Свет был N часов (если отключения были).
Команды: запускал X сцен. Завтра в календаре — Y событий. Спокойной».

Один заход в день, идемпотентность через EventLog marker.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger()


async def send_evening_recap(
    devops_agent: Any,
    calendar_agent: Any,
    memory: Any,
) -> None:
    try:
        from sqlalchemy import select, insert
        from src.db.models import EventLog, PowerOutage, AutomationRule
        from src.utils.time import now_kyiv, iso_now

        now = now_kyiv()
        today_key = now.strftime("%Y-%m-%d")
        marker = f"evening_recap_sent:{today_key}"

        # Идемпотентность
        async with memory._engine.connect() as conn:
            existing = (await conn.execute(
                select(EventLog).where(EventLog.message == marker).limit(1)
            )).first()
        if existing:
            return

        # Данные дня
        start_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        async with memory._engine.connect() as conn:
            outages = list(await conn.execute(
                select(PowerOutage).where(PowerOutage.started_at >= start_iso)
            ))
            still_open = list(await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None))
            ))
            rules_fired = list(await conn.execute(
                select(AutomationRule)
                .where(AutomationRule.last_fired_at >= start_iso)
            ))

        total_outage_min = 0
        for o in outages:
            if o.duration_min:
                total_outage_min += o.duration_min
        if still_open:
            from datetime import datetime as _dt
            for o in still_open:
                try:
                    started = _dt.fromisoformat(o.started_at)
                    total_outage_min += int((now - started).total_seconds() / 60)
                except Exception:
                    pass

        outage_line = ""
        if total_outage_min > 0:
            h, m = total_outage_min // 60, total_outage_min % 60
            outage_line = f"⚡ Свет: отключений на {h}ч {m:02d}м" if h else f"⚡ Свет: отключений на {m}м"
        elif outages:
            outage_line = "⚡ Свет: были короткие отключения"
        else:
            outage_line = "⚡ Свет: стабильно весь день"

        rules_line = ""
        if rules_fired:
            rules_line = f"⚙️ Автоматизации: {len(rules_fired)} сработали"

        # Завтрашний план — пара ближайших событий
        plan_line = ""
        try:
            if calendar_agent and calendar_agent._calendar:
                events = await calendar_agent._calendar.list_upcoming(days=2)
                tomorrow = (now + timedelta(days=1)).date()
                tomorrow_evs = [
                    e for e in events
                    if e.start.date() == tomorrow
                ][:3]
                if tomorrow_evs:
                    plan_line = "📅 Завтра:\n" + "\n".join(
                        f"   • {e.start.strftime('%H:%M')} — {e.title}"
                        for e in tomorrow_evs
                    )
        except Exception:
            log.exception("evening_recap_plan_failed")

        # Сборка
        parts = ["🌙 <b>День прошёл</b>"]
        if outage_line:
            parts.append(outage_line)
        if rules_line:
            parts.append(rules_line)
        if plan_line:
            parts.append(plan_line)
        parts.append("Спокойной ночи. Если что — я тут.")
        text = "\n\n".join(parts)

        try:
            await devops_agent.send(text)
        except Exception:
            log.exception("evening_recap_send_failed")
            return

        # Marker — чтоб не повторяться
        async with memory._engine.begin() as conn:
            await conn.execute(insert(EventLog).values(
                created_at=iso_now(),
                level="INFO",
                message=marker,
            ))
        log.info("evening_recap_sent", outage_min=total_outage_min,
                 rules=len(rules_fired))
    except Exception:
        log.exception("evening_recap_failed")


def register_evening_recap_job(scheduler, devops_agent, calendar_agent, memory) -> None:
    scheduler.add_job(
        send_evening_recap, "cron", hour=22, minute=0,
        args=[devops_agent, calendar_agent, memory],
        id="evening_recap", replace_existing=True,
    )
    log.info("evening_recap_registered")
