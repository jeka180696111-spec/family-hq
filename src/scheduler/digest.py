from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.agents.news import NewsAgent
    from src.db.memory import SharedMemory

log = structlog.get_logger()


async def send_morning_digest(news_agent: "NewsAgent", memory: "SharedMemory") -> None:
    """
    Send the morning news digest.
    Scheduled daily at 08:00 Kyiv time.

    Pulls recent news_posts from DB, asks Claude (via news agent)
    to summarize, sends to group.
    """
    log.info("digest_starting")
    try:
        # Check if there's an active alert — if so, delay 30 min
        async with memory._engine.connect() as conn:
            from src.db.models import ActiveAlert
            from sqlalchemy import select

            alerts = await conn.execute(select(ActiveAlert))
            active = list(alerts)

        if active:
            log.info("digest_delayed_due_to_alert", count=len(active))
            # Scheduler will call again via the rescheduled job
            return

        # Get last 24h news from DB
        async with memory._engine.connect() as conn:
            from datetime import datetime, timedelta

            from sqlalchemy import select

            from src.db.models import NewsPost
            from src.utils.time import KYIV_TZ

            # 10h window covers the user's sleep cycle (22:00 → 08:00)
            since = (datetime.now(KYIV_TZ) - timedelta(hours=10)).isoformat()
            rows = await conn.execute(
                select(NewsPost)
                .where(NewsPost.date >= since)
                .order_by(NewsPost.date.desc())
                .limit(100)
            )
            posts = list(rows)

        if not posts:
            await news_agent.send("📰 Доброе утро! За ночь значимых событий не зафиксировано. 😌")
            return

        news_text = "\n".join(f"[{p.date[11:16]}] {p.text[:200]}" for p in posts[:50])

        response = await news_agent._claude.complete(
            model=news_agent._get_model(),
            system=news_agent.get_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": f"Сформируй утренний дайджест на основе этих новостей за ночь:\n\n{news_text}",
                }
            ],
            max_tokens=1024,
        )
        await news_agent.send(f"📰 Утренний дайджест:\n\n{response}")
        log.info("digest_sent")

    except Exception:
        log.exception("digest_failed")


def register_digest_job(
    scheduler,
    news_agent,
    memory,
    digest_time: str = "08:00",
) -> None:
    """Register the morning digest job with APScheduler."""
    hour, minute = map(int, digest_time.split(":"))
    scheduler.add_job(
        send_morning_digest,
        "cron",
        hour=hour,
        minute=minute,
        timezone="Europe/Kiev",
        args=[news_agent, memory],
        id="morning_digest",
        replace_existing=True,
    )
    log.info("digest_job_registered", time=digest_time)


async def send_baby_morning_digest(nanny_agent, memory) -> None:
    """Daily ~09:00 summary of baby's day from Дневник sheet."""
    try:
        if not nanny_agent._sheets:
            log.info("baby_digest_skipped_no_sheets")
            return

        from datetime import timedelta
        from src.integrations.history_search import _search_sheet
        from src.utils.time import now_kyiv
        cutoff = now_kyiv() - timedelta(hours=18)  # yesterday evening → today morning
        rows = await _search_sheet(nanny_agent._sheets, "Дневник", "", cutoff, 200)
        if not rows:
            await nanny_agent.send("🤱 Доброе утро! За ночь записей нет — поделись как малыш спал.")
            return

        # Summarize via Claude
        import json
        prompt = (
            "На основе записей дневника малыша за прошедшие 18 часов сделай короткую сводку. "
            "Структура: 😴 сон (сколько раз/общая длительность ночь+день), 🍼 кормления "
            "(сколько раз, грудь Л/П/смесь, мл если указано), 💧 подгузники (количество, "
            "был ли кал), особенности (температура/симптомы/вехи если есть). "
            "Без воды. Без выдумок. Если каких-то данных нет — пропусти секцию.\n\n"
            f"ЗАПИСИ:\n{json.dumps(rows, ensure_ascii=False, default=str)[:5000]}"
        )
        response = await nanny_agent._claude.complete(
            model=nanny_agent._get_model(),
            system="Ты — Няня. Краткая ежедневная сводка по малышу. Тёплый тон, но по делу.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
        )
        await nanny_agent.send(f"🤱 Доброе утро! Сводка за ночь и утро:\n\n{response.strip()}")
        log.info("baby_digest_sent", rows=len(rows))
    except Exception:
        log.exception("baby_digest_failed")


def register_baby_digest_job(scheduler, nanny_agent, memory, digest_time: str = "09:00") -> None:
    hour, minute = map(int, digest_time.split(":"))
    scheduler.add_job(
        send_baby_morning_digest,
        "cron",
        hour=hour,
        minute=minute,
        timezone="Europe/Kiev",
        args=[nanny_agent, memory],
        id="baby_morning_digest",
        replace_existing=True,
    )
    log.info("baby_digest_job_registered", time=digest_time)
