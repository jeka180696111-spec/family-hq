"""Wave 3 scheduler jobs: weekly digest, today-important, year-ago-today, quiet hours."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


# ─── Quiet hours filter ────────────────────────────────────────────────

def is_quiet_now(now: datetime | None = None) -> bool:
    """Return True if we should suppress non-critical pushes.

    Default rule: 23:00 → 08:00 every day, Saturday morning until 10:00.
    Тревоги (alerts) и rolling alert updates bypass quiet hours — caller decides.
    """
    from src.utils.time import now_kyiv
    n = now or now_kyiv()
    h = n.hour
    if h >= 23 or h < 8:
        return True
    # Saturday morning
    if n.weekday() == 5 and h < 10:
        return True
    return False


# ─── «Что сегодня важного» — 08:00 daily ───────────────────────────────

async def send_today_important(news_agent, nanny_agent, calendar_agent, memory) -> None:
    """Combined morning brief: news digest (last 10h) + baby summary + today's events + shopping."""
    try:
        from datetime import date
        from sqlalchemy import select
        from src.db.models import NewsPost, ShoppingItem
        from src.utils.time import KYIV_TZ, now_kyiv

        now = now_kyiv()
        ten_h = (now - timedelta(hours=10)).isoformat()

        # 1) News last 10h
        async with memory._engine.connect() as conn:
            news_rows = list(await conn.execute(
                select(NewsPost).where(NewsPost.date >= ten_h)
                .order_by(NewsPost.date.desc()).limit(100)
            ))

        # 2) Calendar events today
        events_text = ""
        if calendar_agent._calendar:
            try:
                events = await calendar_agent._calendar.list_upcoming(days=1)
                events_text = "\n".join(
                    f"  • {e.start.strftime('%H:%M')} {e.title}"
                    for e in events[:10]
                )
            except Exception:
                pass

        # 3) Shopping list
        async with memory._engine.connect() as conn:
            shop_rows = list(await conn.execute(
                select(ShoppingItem).where(ShoppingItem.done_at.is_(None))
            ))

        # 4) Year ago today (Дневник milestones)
        year_ago = ""
        try:
            if nanny_agent._sheets:
                from src.integrations.history_search import _search_sheet
                target = (now - timedelta(days=365)).strftime("%d.%m.%Y")
                hits = await _search_sheet(nanny_agent._sheets, "Достижения", target, datetime(2020, 1, 1), 10)
                if hits:
                    year_ago = "\n".join(f"  • {h.get('Достижение', '')}" for h in hits[:5])
        except Exception:
            pass

        # 5) Compose via Claude
        news_text = "\n".join(f"[{p.date[11:16]}] {p.text[:200]}" for p in news_rows[:40])
        shop_text = "\n".join(
            f"  • {r.item}" + (f" ({r.place})" if r.place else "")
            for r in shop_rows[:15]
        )
        prompt = (
            "Сделай ЕДИНУЮ утреннюю сводку «Что сегодня важного». Структура:\n"
            "📰 Новости за ночь (главное, без воды, по регионам если уместно)\n"
            "📅 На сегодня в календаре (если события есть)\n"
            "🛒 Купить (если в списке что-то есть)\n"
            "🎂 Год назад в этот день (если есть данные)\n"
            "Без вступления и заключения, без эмодзи в начале каждой строки внутри секций.\n\n"
            f"НОВОСТИ:\n{news_text or 'ничего'}\n\n"
            f"КАЛЕНДАРЬ:\n{events_text or 'пусто'}\n\n"
            f"ПОКУПКИ:\n{shop_text or 'пусто'}\n\n"
            f"ГОД НАЗАД:\n{year_ago or 'нет данных'}"
        )
        response = await news_agent._claude.complete(
            model=news_agent._get_model(),
            system="Ты — Дозорный. Свод утренней брифинг-сводки для семьи. Кратко, по делу.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
        )
        await news_agent.send(f"☀️ Что сегодня важного — {now.strftime('%d.%m.%Y, %A')}\n\n{response.strip()}")
        log.info("today_important_sent")
    except Exception:
        log.exception("today_important_failed")


def register_today_important_job(scheduler, news_agent, nanny_agent, calendar_agent, memory) -> None:
    scheduler.add_job(
        send_today_important,
        "cron", hour=8, minute=0, timezone="Europe/Kiev",
        args=[news_agent, nanny_agent, calendar_agent, memory],
        id="today_important", replace_existing=True,
    )
    log.info("today_important_job_registered")


# ─── Weekly digest — Sunday 10:00 ──────────────────────────────────────

async def send_weekly_digest(news_agent, nanny_agent, memory) -> None:
    """Big Sunday overview: baby trends, news highlights, expenses if available."""
    try:
        from datetime import date, datetime, timedelta
        from sqlalchemy import select
        from src.db.models import ApiUsage, NewsPost, ShoppingItem
        from src.utils.time import now_kyiv

        now = now_kyiv()
        week_ago = (now - timedelta(days=7)).isoformat()
        week_ago_date = (date.today() - timedelta(days=7)).isoformat()

        # Baby data from Дневник — реальные строки, не счётчики
        diary_text = ""
        feeding_text = ""
        growth_text = ""
        milestones_text = ""
        if nanny_agent._sheets:
            try:
                from src.integrations.history_search import _search_sheet
                cutoff = now - timedelta(days=7)
                diary = await _search_sheet(nanny_agent._sheets, "Дневник", "", cutoff, 200)
                feeding = await _search_sheet(nanny_agent._sheets, "Прикорм", "", cutoff, 50)
                growth = await _search_sheet(nanny_agent._sheets, "Рост", "", cutoff, 5)
                milestones = await _search_sheet(nanny_agent._sheets, "Достижения", "", cutoff, 20)
                # Реальные строки до 60 шт, обрезанные
                diary_text = "\n".join(
                    f"  · {row.get('date','')} {row.get('time','')} {row.get('kind','')} — {row.get('event','')[:80]}"
                    for row in diary[-60:]
                ) or "  (записей нет)"
                feeding_text = "\n".join(
                    f"  · {row.get('Дата','')} {row.get('Продукт','')} · реакция: {row.get('Реакция','')[:60]}"
                    for row in feeding[-30:]
                ) or "  (новых продуктов не вводили)"
                growth_text = "\n".join(
                    f"  · {row.get('Дата','')} вес {row.get('Вес','')} рост {row.get('Рост','')}"
                    for row in growth
                ) or "  (замеров не было)"
                milestones_text = "\n".join(
                    f"  · {row.get('Дата','')} — {row.get('Достижение','')[:120]}"
                    for row in milestones[-15:]
                ) or "  (новых достижений не отмечено)"
            except Exception:
                log.exception("weekly_baby_failed")
                diary_text = "  (ошибка чтения Дневника)"

        # News alerts (with regions)
        async with memory._engine.connect() as conn:
            alerts = list(await conn.execute(
                select(NewsPost).where(NewsPost.date >= week_ago)
                .where(NewsPost.is_alert == 1).order_by(NewsPost.date.desc()).limit(200)
            ))
            shop_done = list(await conn.execute(
                select(ShoppingItem).where(ShoppingItem.done_at >= week_ago_date)
            ))
            shop_open = list(await conn.execute(
                select(ShoppingItem).where(ShoppingItem.done_at.is_(None)).limit(20)
            ))
            api = list(await conn.execute(
                select(ApiUsage).where(ApiUsage.date >= week_ago_date)
            ))

        api_in = sum(r.input_tokens for r in api)
        api_out = sum(r.output_tokens for r in api)
        # Оценочная стоимость по Sonnet 4.5: $3/M input, $15/M output
        api_cost = api_in / 1_000_000 * 3 + api_out / 1_000_000 * 15

        shop_done_text = "\n".join(f"  · {r.item}" for r in shop_done[-15:]) or "  (закрытых покупок нет)"
        shop_open_text = "\n".join(f"  · {r.item}" + (f" [{r.place}]" if r.place else "") for r in shop_open) or "  (список пуст)"

        # Calendar на следующие 7 дней — для секции «На следующую неделю»
        next_week_events = ""
        try:
            # nanny_agent has no calendar; нужно вытащить из настроек.
            from src.config import get_settings
            from src.integrations.gcalendar import CalendarClient
            settings = get_settings()
            if settings.google_service_account_json and settings.calendar_id:
                cal = CalendarClient(settings.google_service_account_json, settings.calendar_id)
                evs = await cal.list_upcoming(days=7)
                next_week_events = "\n".join(
                    f"  · {e.start.strftime('%d.%m %H:%M')} — {e.title}"
                    for e in evs[:15]
                ) or "  (в календаре пусто на эту неделю)"
        except Exception:
            log.exception("weekly_calendar_failed")
            next_week_events = "  (календарь недоступен)"

        prompt = (
            "Воскресный итог недели для семьи Евгения и Марины (Матвей, 6 мес).\n\n"
            "ЖЁСТКИЕ ПРАВИЛА:\n"
            "1. НИКАКИХ ПЛЕЙСХОЛДЕРОВ. Запрещено писать «[вставить продукт]», "
            "«[Дата]», «[навык]» — это галлюцинация. Если данных нет — ЧЕСТНО "
            "скажи «нет записей за эту неделю».\n"
            "2. Только то, что ЕСТЬ в данных ниже. Не выдумывай прививки, "
            "достижения, события, тенденции которых не было.\n"
            "3. Стоимость API считай по реальным цифрам что я дал.\n"
            "4. Тон — старший брат-наблюдатель. Без штамповки.\n\n"
            "СТРУКТУРА:\n"
            "👶 МАЛЫШ — реальные тренды по diary, реальные новые продукты, реальные достижения\n"
            "📰 ОБСТАНОВКА — тревоги (точное число), без пафоса\n"
            "🛒 БЫТОВОЕ — что куплено, что осталось в списке (реальные позиции)\n"
            "💸 СИСТЕМА — токены, стоимость, проблемы недели если были\n"
            "🔮 НА СЛЕДУЮЩУЮ НЕДЕЛЮ — реальные события из календаря\n\n"
            "═══ ДАННЫЕ ═══\n\n"
            f"ДНЕВНИК МАТВЕЯ (последние 60 записей):\n{diary_text}\n\n"
            f"НОВЫЕ ПРОДУКТЫ ПРИКОРМА:\n{feeding_text}\n\n"
            f"РОСТ/ВЕС (замеры):\n{growth_text}\n\n"
            f"ДОСТИЖЕНИЯ:\n{milestones_text}\n\n"
            f"ВОЗДУШНЫЕ ТРЕВОГИ ЗА НЕДЕЛЮ: {len(alerts)}\n\n"
            f"ПОКУПКИ — закрыто за неделю:\n{shop_done_text}\n\n"
            f"ПОКУПКИ — осталось в списке:\n{shop_open_text}\n\n"
            f"API ТОКЕНЫ: in={api_in:,} out={api_out:,}\n"
            f"СТОИМОСТЬ API ОЦЕНОЧНО: ${api_cost:.2f}\n\n"
            f"КАЛЕНДАРЬ НА БЛИЖАЙШИЕ 7 ДНЕЙ:\n{next_week_events}"
        )
        response = await news_agent._claude.complete(
            model=news_agent._get_model(),
            system=(
                "Ты — Дозорный. Воскресный обзор семьи. РАБОТАЕШЬ ТОЛЬКО "
                "С ДАННЫМИ ИЗ ПРОМПТА. Никаких плейсхолдеров, никакой "
                "выдумки. Если поле пусто — скажи что нет данных, не "
                "придумывай содержимое."
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        # Anti-placeholder guard — на случай если LLM всё-таки протёк
        out = response.strip()
        if any(marker in out for marker in ("[вставить", "[Дата]", "[Date]", "[insert", "[вписать", "[название")):
            log.warning("weekly_digest_placeholder_detected", excerpt=out[:200])
            out = (
                "⚠️ Не смог собрать корректный отчёт — данные неполные. "
                "Реальные цифры:\n"
                f"• Тревог: {len(alerts)}\n"
                f"• Покупок закрыто: {len(shop_done)}\n"
                f"• API: {api_in:,} in / {api_out:,} out (≈${api_cost:.2f})\n\n"
                "Дневник Матвея, достижения и календарь — смотри в Sheets/Drive."
            )
        await news_agent.send(f"🗓 ИТОГИ НЕДЕЛИ ({now.strftime('%d.%m')}):\n\n{out}")
        log.info("weekly_digest_sent")
    except Exception:
        log.exception("weekly_digest_failed")


def register_weekly_digest_job(scheduler, news_agent, nanny_agent, memory) -> None:
    scheduler.add_job(
        send_weekly_digest,
        "cron", day_of_week="sun", hour=10, minute=0, timezone="Europe/Kiev",
        args=[news_agent, nanny_agent, memory],
        id="weekly_digest", replace_existing=True,
    )
    log.info("weekly_digest_job_registered")


# ─── Baby budget alert — daily check around 18:00 ──────────────────────

async def check_baby_budget(devops_agent, memory) -> None:
    """If ≥25% of month left but ≤25% of baby budget remains, ping the group."""
    try:
        # Asks user's external Фінн for current spending — we don't have access.
        # Instead, use a heuristic via Прораб's prompt: it will compute from
        # configured monthly budget and known recent expense markers if available.
        # For now: emit a soft 'check your budget' note if late in month.
        from datetime import date
        from calendar import monthrange
        from src.utils.family import FINANCE

        today = date.today()
        total_days = monthrange(today.year, today.month)[1]
        days_left = total_days - today.day
        if days_left == 7:  # 1 week to month end
            await devops_agent.send(
                f"💸 <b>Контроль бюджета</b>\n"
                f"До конца месяца неделя. Ориентир по малышу: {FINANCE['monthly_baby_budget']} UAH/мес.\n"
                f"Спроси у Фінна сколько потрачено: «фінн, скільки витратили на малюка цього місяця?»"
            )
            log.info("baby_budget_alert_sent")
    except Exception:
        log.exception("baby_budget_alert_failed")


def register_baby_budget_job(scheduler, devops_agent, memory) -> None:
    scheduler.add_job(
        check_baby_budget,
        "cron", hour=18, minute=0, timezone="Europe/Kiev",
        args=[devops_agent, memory],
        id="baby_budget_alert", replace_existing=True,
    )
    log.info("baby_budget_job_registered")


# ─── Time capsule resurfacing — daily check for anniversaries ──────────

async def check_time_capsules(news_agent, memory) -> None:
    """If any time_capsule entry was made N years ago today, resurface it."""
    try:
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from src.db.models import EventLog
        from src.utils.time import now_kyiv

        today = now_kyiv().date()
        async with memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(EventLog).where(EventLog.event == "time_capsule")
            ))
        hits = []
        for r in rows:
            try:
                created = datetime.fromisoformat(r.created_at).date()
            except Exception:
                continue
            anniv_years = today.year - created.year
            if anniv_years <= 0:
                continue
            if created.month == today.month and created.day == today.day:
                hits.append({"years_ago": anniv_years, "text": r.message, "date": created.isoformat()})
        if not hits:
            return
        lines = ["📜 <b>Капсула времени</b>"]
        for h in hits:
            label = "год" if h["years_ago"] == 1 else "года" if h["years_ago"] < 5 else "лет"
            lines.append(f"\n<b>{h['years_ago']} {label} назад в этот день:</b>\n{h['text']}")
        await news_agent.send("\n".join(lines))
        log.info("time_capsules_resurfaced", count=len(hits))
    except Exception:
        log.exception("time_capsule_check_failed")


def register_time_capsule_job(scheduler, news_agent, memory) -> None:
    scheduler.add_job(
        check_time_capsules,
        "cron", hour=9, minute=30, timezone="Europe/Kiev",
        args=[news_agent, memory],
        id="time_capsule_check", replace_existing=True,
    )
    log.info("time_capsule_job_registered")
