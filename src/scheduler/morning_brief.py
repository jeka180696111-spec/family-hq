"""Unified morning brief — single 07:00 message from Прораб aggregating
news, weather (with clothing & walk-window suggestions for parents and baby),
baby summary, today's plans, and systems health.

Replaces the older separate 08:00/09:00 digests.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select

log = structlog.get_logger()


# ─── Section: news ───────────────────────────────────────────────────

async def _section_news(news_agent: Any, memory: Any) -> str:
    try:
        from src.db.models import NewsPost
        from src.utils.time import now_kyiv
        since = (now_kyiv() - timedelta(hours=12)).isoformat()
        async with memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(NewsPost).where(NewsPost.date >= since)
                .order_by(NewsPost.date.desc()).limit(80)
            ))
        if not rows:
            return "🛡 <b>За ночь — тихо.</b> Значимых событий нет."
        news_text = "\n".join(f"[{p.date[11:16]}] {p.text[:180]}" for p in rows[:40])
        prompt = (
            "Сделай очень короткий ночной дайджест для семьи в Одессе. "
            "3-5 пунктов max, только реально важное (тревоги/удары/решения по городу). "
            "Без воды. Без эмодзи в начале каждой строки.\n\n"
            f"СООБЩЕНИЯ:\n{news_text}"
        )
        text = await news_agent._claude.complete(
            model=news_agent._get_model(),
            system="Ты — Дозорный. Сухая фактура для утреннего брифинга.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        return f"🛡 <b>За ночь</b>\n{text.strip()}"
    except Exception:
        log.exception("brief_news_failed")
        return ""


# ─── Section: weather + clothing + walk window ───────────────────────

def _adult_clothing(temp: float, wind: float, rain: float, code: int | None) -> str:
    parts = []
    if temp < -5:    parts.append("пуховик, шапка, перчатки")
    elif temp < 5:   parts.append("тёплая куртка, шапка")
    elif temp < 12:  parts.append("куртка/пальто")
    elif temp < 18:  parts.append("лёгкая куртка или худи")
    elif temp < 24:  parts.append("футболка + лёгкая кофта")
    else:            parts.append("лёгкая одежда")
    if wind >= 10:   parts.append("ветровка")
    accessories = []
    if rain >= 0.3:  accessories.append("☂️ зонт")
    if code is not None and code in (0, 1) and temp >= 18:
        accessories.append("😎 очки")
    if temp < 0:     accessories.append("🧤 перчатки")
    suffix = (" + " + ", ".join(accessories)) if accessories else ""
    return ", ".join(parts) + suffix


def _baby_clothing(temp: float) -> str:
    # 6-months baby: stroller layers; +1 layer rule vs adult
    if temp < 0:     return "комбинезон зимний, шапка, варежки, пинетки тёплые"
    if temp < 8:     return "тёплый комбинезон, шапка, носочки"
    if temp < 15:    return "демисезонный комбинезон, лёгкая шапочка"
    if temp < 20:    return "боди + лёгкий комбинезон/кофта"
    if temp < 26:    return "боди + тонкий комбинезон, панамка"
    return "лёгкое боди, панамка, в тени"


def _walk_window(hourly: list[dict]) -> str:
    """Pick best contiguous slot 7:00-20:00 today where:
       8 ≤ temp ≤ 27, rain<0.2mm, wind<12m/s, no thunderstorm code (95-99)."""
    from src.utils.time import now_kyiv
    today_str = now_kyiv().strftime("%Y-%m-%d")
    candidates = []
    for h in hourly:
        t = h.get("time") or ""
        if not t.startswith(today_str):
            continue
        try:
            hh = int(t[11:13])
        except Exception:
            continue
        if hh < 7 or hh > 20:
            continue
        temp = h.get("temp_c") or 0
        rain = h.get("rain_mm") or 0
        wind = h.get("wind_ms") or 0
        code = h.get("description", "")
        bad = (temp < 8 or temp > 27 or rain >= 0.2 or wind >= 12
               or "Гроза" in code or "Ливн" in code)
        candidates.append((hh, not bad))
    if not candidates:
        return ""
    # Find longest contiguous OK run
    best_start = best_len = cur_start = cur_len = -1
    for hh, ok in candidates:
        if ok:
            if cur_len < 0:
                cur_start, cur_len = hh, 1
            else:
                cur_len += 1
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
        else:
            cur_len = -1
    if best_len < 1:
        return "🚶 Сегодня гулять не стоит — погода против."
    return f"🚶 Окно прогулки: {best_start:02d}:00–{best_start + best_len:02d}:00"


async def _section_weather() -> str:
    try:
        from src.config import get_settings
        from src.integrations.weather import WeatherClient
        client = WeatherClient.from_settings(get_settings())
        if not client:
            return ""
        cur = await client.current()
        hourly = await client.forecast(hours=18)
        temp = cur.get("temp_c", 0) or 0
        feels = cur.get("feels_like_c", temp) or temp
        wind = cur.get("wind_ms", 0) or 0
        desc = cur.get("description", "")
        # Day extremes from hourly (current day only)
        from src.utils.time import now_kyiv
        today_prefix = now_kyiv().strftime("%Y-%m-%d")
        today_temps = [h["temp_c"] for h in hourly
                       if (h.get("time") or "").startswith(today_prefix)
                       and h.get("temp_c") is not None]
        rain_total = sum((h.get("rain_mm") or 0) for h in hourly
                         if (h.get("time") or "").startswith(today_prefix))
        max_pop = max((h.get("pop_pct") or 0) for h in hourly
                      if (h.get("time") or "").startswith(today_prefix)) if today_temps else 0
        day_max = max(today_temps) if today_temps else temp
        day_min = min(today_temps) if today_temps else temp
        wcode = None  # not exposed cleanly; pass description through
        adult = _adult_clothing(temp, wind, rain_total, wcode)
        baby = _baby_clothing((temp + day_max) / 2)
        walk = _walk_window(hourly)

        lines = [
            f"🌤 <b>Погода</b> ({cur.get('city', 'Одесса')})",
            f"Сейчас {temp:+.0f}° (ощущается {feels:+.0f}°), {desc.lower() or '—'}",
            f"Днём {day_min:+.0f}…{day_max:+.0f}°, дождь {rain_total:.1f}мм (вероятность до {int(max_pop)}%)",
            f"👤 Одеться: {adult}",
            f"👶 Малышу: {baby}",
        ]
        if walk:
            lines.append(walk)
        return "\n".join(lines)
    except Exception:
        log.exception("brief_weather_failed")
        return ""


# ─── Section: baby ────────────────────────────────────────────────────

async def _section_baby(nanny_agent: Any, memory: Any) -> str:
    try:
        if not nanny_agent._sheets:
            return ""
        from src.integrations.history_search import _search_sheet
        from src.utils.time import now_kyiv
        cutoff = now_kyiv() - timedelta(hours=14)
        rows = await _search_sheet(nanny_agent._sheets, "Дневник", "", cutoff, 200)
        nursery = ""
        try:
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            t = TuyaClient.from_settings(get_settings())
            if t:
                reading = await t.read_sensor("детская")
                if reading and "error" not in reading:
                    nursery = reading.get("formatted", "")
        except Exception:
            log.exception("brief_baby_sensor_failed")

        if not rows:
            tail = f"\n{nursery}" if nursery else ""
            return f"🤱 <b>Малыш</b>\nЗа ночь записей нет.{tail}"
        prompt = (
            "Короткая сводка по малышу за ночь — 2-4 строки. "
            "😴 сон (раз/общая длительность), 🍼 кормления (раз+формат), "
            "💧 подгузники (число+был ли кал), особенности если есть. Без воды.\n\n"
            f"ЗАПИСИ:\n{json.dumps(rows, ensure_ascii=False, default=str)[:4000]}"
        )
        summary = await nanny_agent._claude.complete(
            model=nanny_agent._get_model(),
            system="Ты — Няня. Очень короткая фактура для утреннего брифинга.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
        )
        tail = f"\n{nursery}" if nursery else ""
        return f"🤱 <b>Малыш</b>\n{summary.strip()}{tail}"
    except Exception:
        log.exception("brief_baby_failed")
        return ""


# ─── Section: plans ──────────────────────────────────────────────────

async def _section_plans(calendar_agent: Any, memory: Any) -> str:
    try:
        client = getattr(calendar_agent, "_calendar", None)
        if not client:
            return ""
        events = await client.list_upcoming(days=1)
        from src.utils.time import now_kyiv
        today = now_kyiv().date()
        today_events = []
        for e in events:
            start = getattr(e, "start", None)
            if not start:
                continue
            if hasattr(start, "date") and start.date() == today:
                hhmm = start.strftime("%H:%M") if hasattr(start, "strftime") else ""
                today_events.append(f"• {hhmm} {getattr(e, 'title', '')}")
        if not today_events:
            return "📅 <b>Планы</b>\nСвободный день."
        return "📅 <b>Планы</b>\n" + "\n".join(today_events[:8])
    except Exception:
        log.exception("brief_plans_failed")
        return ""


# ─── Section: systems ────────────────────────────────────────────────

async def _section_systems(memory: Any) -> str:
    try:
        from src.config import get_settings
        from src.db.models import AutomationRule, EventLog, PowerOutage, ActiveAlert
        from src.utils.time import now_kyiv
        settings = get_settings()
        lines = []

        # Inverter
        lux_battery = None
        lux_state = "?"
        try:
            from src.integrations.luxcloud import LuxCloudClient
            lux = LuxCloudClient.from_settings(settings)
            if lux:
                rt = await lux.runtime()
                lux_battery = rt.get("battery_pct")
                lux_state = "на батарее" if (rt.get("battery_discharge_w") or 0) > 30 else "сеть"
        except Exception:
            lux_state = "недоступен"

        # Active outage
        async with memory._engine.connect() as conn:
            outage_row = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None)).limit(1)
            )).first()
            alert_row = (await conn.execute(select(ActiveAlert).limit(1))).first()
            rules = list(await conn.execute(
                select(AutomationRule).where(AutomationRule.enabled == 1)
            ))
            since = (now_kyiv() - timedelta(hours=24)).isoformat()
            errs = list(await conn.execute(
                select(EventLog).where(EventLog.level.in_(("ERROR", "CRITICAL")))
                .where(EventLog.created_at >= since)
            ))

        if outage_row:
            lines.append("⚡ <b>Свет</b>: нет (на батарее)")
        else:
            lines.append("⚡ <b>Свет</b>: есть")
        if lux_battery is not None:
            lines.append(f"🔋 Инвертор: {int(lux_battery)}% ({lux_state})")
        if alert_row:
            lines.append(f"🚨 Тревога активна: {alert_row.region}")
        fires_24h = sum(getattr(r, "fired_count", 0) or 0 for r in rules)  # cumulative — approx
        lines.append(f"🤖 Автоматизаций: {len(rules)} активных")
        if errs:
            lines.append(f"⚠️ Ошибок за сутки: {len(errs)}")
        else:
            lines.append("✅ Ошибок нет")
        return "🛠 <b>Системы</b>\n" + "\n".join(lines)
    except Exception:
        log.exception("brief_systems_failed")
        return ""


# ─── Main: compose & send ────────────────────────────────────────────

async def send_morning_brief(
    devops_agent: Any,
    news_agent: Any,
    nanny_agent: Any,
    calendar_agent: Any,
    memory: Any,
) -> None:
    try:
        from src.utils.time import now_kyiv
        date_str = now_kyiv().strftime("%d.%m, %A")
        # Run sections in parallel where independent
        import asyncio
        news_s, weather_s, baby_s, plans_s, systems_s = await asyncio.gather(
            _section_news(news_agent, memory),
            _section_weather(),
            _section_baby(nanny_agent, memory),
            _section_plans(calendar_agent, memory),
            _section_systems(memory),
            return_exceptions=False,
        )
        sections = [s for s in (news_s, weather_s, baby_s, plans_s, systems_s) if s]
        header = f"☀️ <b>Доброе утро!</b> Сводка на {date_str}"
        body = "\n\n".join([header] + sections)
        await devops_agent.send(body)
        log.info("morning_brief_sent", sections=len(sections))
    except Exception:
        log.exception("morning_brief_failed")


def register_morning_brief_job(
    scheduler,
    devops_agent,
    news_agent,
    nanny_agent,
    calendar_agent,
    memory,
    at: str = "07:00",
) -> None:
    h, m = map(int, at.split(":"))
    scheduler.add_job(
        send_morning_brief,
        "cron", hour=h, minute=m, timezone="Europe/Kiev",
        args=[devops_agent, news_agent, nanny_agent, calendar_agent, memory],
        id="morning_brief", replace_existing=True,
    )
    log.info("morning_brief_registered", at=at)
