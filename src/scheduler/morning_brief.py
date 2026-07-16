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
            system=(
                "Ты — Дозорный. Сухая фактура для утреннего брифинга. "
                "ВСЕГДА пиши ТОЛЬКО НА РУССКОМ, даже если исходные "
                "сообщения на украинском или английском. Не смешивай "
                "языки."
            ),
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

async def _section_recent_vaccinations(memory: Any) -> str:
    """Если за последние 3 дня была прививка — спрашиваем у Марины
    как реакция (температура, аппетит, капризы). Идемпотентно: для
    каждого вакцинного события показываем напоминание ровно 3 утра
    после прививки."""
    try:
        from src.config import get_settings
        from src.integrations.gcalendar import CalendarClient
        from src.utils.time import now_kyiv
        s = get_settings()
        if not (s.google_service_account_json and s.calendar_id):
            return ""
        cal = CalendarClient(s.google_service_account_json, s.calendar_id)
        events = await cal.list_recent(days_back=3)
    except Exception:
        log.exception("brief_vaccinations_failed")
        return ""

    now = now_kyiv().date()
    interesting = []
    for e in events:
        title = (getattr(e, "title", "") or "")
        low = title.lower()
        if not ("прививк" in low or "вакц" in low or "💉" in title or "акдс" in low):
            continue
        start = getattr(e, "start", None)
        if not start:
            continue
        try:
            d = start.date() if hasattr(start, "date") else start
        except Exception:
            continue
        delta_days = (now - d).days
        if 0 <= delta_days <= 3:
            interesting.append((delta_days, title))

    if not interesting:
        return ""
    interesting.sort()
    lines = ["🩺 <b>После прививки</b>"]
    for days_ago, title in interesting[:3]:
        ago = "сегодня" if days_ago == 0 else (
            "вчера" if days_ago == 1 else f"{days_ago} дня назад"
        )
        clean = title.replace("💉", "").strip()
        lines.append(f"• {clean} ({ago}). Как Матвей? Температура / капризы / аппетит?")
    return "\n".join(lines)


async def _section_sleep_coach(nanny_agent: Any) -> str:
    """Утренняя коротко-сводка от sleep-coach: цифры за неделю + 1-2
    конкретных совета на сегодня. LLM рендерит из summary_for_agent."""
    try:
        if not nanny_agent._sheets:
            return ""
        from src.integrations.sleep_coach import weekly_analysis
        data = await weekly_analysis(nanny_agent._sheets, days=7, memory=getattr(nanny_agent, "_memory", None))
        if not data.get("observed"):
            return ""
        prompt = (
            "Сводка «Сон Матвея» для утреннего брифинга. МАКСИМУМ 2 строки. "
            "Формат:\n"
            "  Ночь: <часы>ч, <кол-во>× пробуждений. Дни: <часы>ч.\n"
            "  Совет: <одна короткая фраза что попробовать сегодня>.\n"
            "Никаких вступлений, метафор, объяснений. Только факты и один совет.\n\n"
            f"ДАННЫЕ:\n{data['summary_for_agent']}"
        )
        text = await nanny_agent._claude.complete(
            model=nanny_agent._get_model(),
            system=(
                "Ты — Няня. МАКСИМУМ 2 строки, без воды. "
                "ВСЕГДА пиши ТОЛЬКО НА РУССКОМ."
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=180,
        )
        if not text:
            return ""
        return f"😴 <b>Сон Матвея</b>\n{text.strip()}"
    except Exception:
        log.exception("brief_sleep_coach_failed")
        return ""


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
            system=(
                "Ты — Няня. Очень короткая фактура для утреннего брифинга. "
                "ВСЕГДА пиши ТОЛЬКО НА РУССКОМ."
            ),
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
    """Health-report — сначала список ПРОБЛЕМ (даже если пусто), потом
    статусы. Задача: чтобы юзер утром сразу видел что упало и что нужно
    сделать — пополнить Claude, продлить Tuya, разобраться с Google auth."""
    problems: list[str] = []  # список конкретных «что делать»
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
        # Инвертор ушёл в секцию «Умный дом» с полными показателями —
        # тут не дублируем.
        if alert_row:
            lines.append(f"🚨 Тревога активна: {alert_row.region}")
        # Tuya health check — реальный тык в облако, не «всё ок по
        # умолчанию». Если quota исчерпана или auth упал — Прораб
        # должен это утром сказать, а не делать вид что всё хорошо.
        try:
            from src.integrations.tuya import TuyaClient
            t = TuyaClient.from_settings(settings)
            if t:
                # 1) Пробуем list_devices — это самый лёгкий вызов.
                list_ok = False
                list_err = ""
                try:
                    await t.list_devices()
                    list_ok = True
                except Exception as e:
                    list_err = str(e)

                # 2) Дополнительно сканируем EventLog за 24ч на
                # признаки Tuya-ошибок квоты/прав/оффлайна. Даже если
                # list_devices прошёл, могло быть что command падает
                # с quota exhausted — тогда Прораб пометит это ошибкой.
                tuya_recent_errs = []
                async with memory._engine.connect() as conn:
                    since_iso = (now_kyiv() - timedelta(hours=24)).isoformat()
                    log_rows = list(await conn.execute(
                        select(EventLog).where(EventLog.created_at >= since_iso)
                    ))
                    for r in log_rows:
                        msg = (r.message or "").lower()
                        payload = (r.payload or "").lower() if hasattr(r, "payload") else ""
                        text = f"{msg} {payload}"
                        if any(sig in text for sig in (
                            "quota is exhausted", "trial quota", "quota exhaust",
                            "no permission", "permission denied",
                            "1106", "28841004",  # Tuya specific error codes
                        )):
                            tuya_recent_errs.append(msg[:80])

                if list_ok and not tuya_recent_errs:
                    lines.append("🏠 Tuya cloud: ок")
                elif tuya_recent_errs:
                    # Есть свежие ошибки квоты — это точно означает
                    # что команды не пройдут.
                    quota_flag = any(
                        "quota" in e or "exhaust" in e or "28841004" in e
                        for e in tuya_recent_errs
                    )
                    perm_flag = any(
                        "permission" in e or "1106" in e
                        for e in tuya_recent_errs
                    )
                    if quota_flag:
                        lines.append("🏠 Tuya cloud: ❌ КВОТА ИСЧЕРПАНА (команды не пройдут до восстановления)")
                    elif perm_flag:
                        lines.append("🏠 Tuya cloud: ❌ нет доступа (проверь подписки)")
                    else:
                        lines.append(f"🏠 Tuya cloud: ❌ ошибки в журнале за сутки ({len(tuya_recent_errs)})")
                else:
                    err = list_err.lower()
                    if "quota" in err or "exhaust" in err:
                        lines.append("🏠 Tuya cloud: ❌ КВОТА ИСЧЕРПАНА")
                    elif "permission" in err or "auth" in err:
                        lines.append("🏠 Tuya cloud: ❌ нет доступа")
                    else:
                        lines.append(f"🏠 Tuya cloud: ❌ {list_err[:80]}")
        except Exception:
            log.exception("brief_tuya_health_failed")

        # === AI-провайдеры ===
        try:
            from src.integrations.claude_client import get_ai_stats
            ai = get_ai_stats()
            current = ai.get("current_provider", "?")
            claude_fail = ai.get("claude_fail_count", 0)
            gemini_fail = ai.get("gemini_fail_count", 0)
            gemini_keys = ai.get("gemini_key_count", 0)
            # Если сейчас работает Gemini а Клод падал — вероятно Клоду нужен top-up
            if current == "gemini" and claude_fail > 0:
                problems.append("💳 Клод упал — вероятно баланс на исходе, пополни на console.anthropic.com")
                lines.append(f"🤖 AI: работает Gemini (Клод падал {claude_fail}× за сессию)")
            elif claude_fail > 0 and current == "claude":
                lines.append(f"🤖 AI: Клод (падал {claude_fail}× но восстановился)")
            else:
                lines.append(f"🤖 AI: {current}")
            if gemini_fail > 3:
                problems.append(f"⚠️ Gemini падал {gemini_fail}× — возможно квота кончилась, проверь ключи")
        except Exception:
            log.exception("brief_ai_health_failed")

        # === LuxCloud ===
        try:
            from src.integrations.luxcloud import LuxCloudClient
            lux = LuxCloudClient.from_settings(settings)
            if lux:
                try:
                    rt = await lux.runtime()
                    if not rt.get("online"):
                        problems.append("📉 LuxCloud считает инвертор оффлайн — проверь WiFi у инвертора")
                except Exception as e:
                    problems.append(f"📉 LuxCloud недоступен: {str(e)[:80]}")
        except Exception:
            log.exception("brief_lux_health_failed")

        # === Google (Sheets/Calendar/Drive) — по ошибкам в логе ===
        google_errs = 0
        for r in errs[-30:]:
            msg = (r.message or "").lower()
            if any(x in msg for x in ("google", "sheets", "calendar", "drive", "gspread", "oauth")):
                google_errs += 1
        if google_errs >= 3:
            problems.append(f"📊 Google API падает ({google_errs}× за сутки) — возможно токен истёк или квота")

        # === Tuya (уже добавлено выше) — если проблема, дублируем в problems ===
        if any("КВОТА ИСЧЕРПАНА" in l for l in lines):
            problems.append("🏠 Tuya: квота исчерпана — команды умного дома не пройдут. Продли триал или пополни.")
        elif any("нет доступа" in l for l in lines if "Tuya" in l):
            problems.append("🏠 Tuya: нет доступа к API — проверь подписки Smart Home Basic / IoT Core")

        fires_24h = sum(getattr(r, "fired_count", 0) or 0 for r in rules)  # cumulative — approx
        lines.append(f"🤖 Автоматизаций: {len(rules)} активных")
        if errs:
            seen = set()
            err_examples = []
            for e in errs[-15:]:
                msg = (e.message or "")[:80]
                if msg in seen:
                    continue
                seen.add(msg)
                err_examples.append(msg)
                if len(err_examples) >= 3:
                    break
            lines.append(f"⚠️ Ошибок за сутки: {len(errs)}")
            for ex in err_examples:
                lines.append(f"  · {ex}")
        elif not problems:
            # «Ошибок нет» пишем ТОЛЬКО если и в problems ничего,
            # иначе противоречие: сверху «⚡ проблема», снизу «всё ок».
            lines.append("✅ Ошибок нет")
        # Если ошибок в EventLog нет но problems есть — вообще молчим
        # про этот статус, не пишем ни «нет» ни «есть».
        # Собираем: сначала блок ПРОБЛЕМ (только если есть), потом статусы
        prefix = ""
        if problems:
            prefix = "🚨 <b>Внимание — проблемы:</b>\n" + "\n".join(f"  • {p}" for p in problems) + "\n\n"
        return "🛠 <b>Системы</b>\n" + prefix + "\n".join(lines)
    except Exception:
        log.exception("brief_systems_failed")
        return ""


# ─── Section: home status (devices, sensors, vacuum, inverter) ───────

def _dps_to_dict(status: list) -> dict:
    """[{code, value}, ...] → {code: value}."""
    return {s.get("code", ""): s.get("value") for s in (status or []) if s.get("code")}


def _format_device_line(name: str, online: bool, dps: dict) -> str:
    """По имени и DPs формируем строку с реальными показателями."""
    low = name.lower()

    if not online:
        return None  # оффлайн-устройства не показываем чтобы не шуметь

    # === Датчик температуры/влажности ===
    if "датчик" in low or "sensor" in low:
        # Tuya DPs: va_temperature (0.1°C), va_humidity, battery_percentage
        temp = dps.get("va_temperature") or dps.get("temp_current")
        humid = dps.get("va_humidity") or dps.get("humidity_value")
        battery = dps.get("battery_percentage") or dps.get("battery_state")
        parts = []
        if temp is not None:
            parts.append(f"{float(temp) / 10:.1f}°C" if abs(temp) > 100 else f"{temp}°C")
        if humid is not None:
            parts.append(f"вл. {humid}%")
        if battery is not None:
            parts.append(f"🔋 {battery}%")
        return f"🌡 {name}: {', '.join(parts) if parts else 'нет данных'}"

    # === Бойлер (розетка с мониторингом) ===
    if "бойлер" in low:
        switch = dps.get("switch") or dps.get("switch_1")
        power = dps.get("cur_power")  # 0.1W
        if power is not None:
            power_w = float(power) / 10 if power > 500 else power
            state = "включён" if switch else "выключен"
            return f"🔥 {name}: {state}, {int(power_w)}Вт"
        return f"🔥 {name}: {'включён' if switch else 'выключен'}"

    # === Кондер ===
    if "кондер" in low or "кондиц" in low:
        switch = dps.get("switch") or dps.get("power")
        mode = dps.get("mode") or dps.get("work_mode") or ""
        temp_set = dps.get("temp_set") or dps.get("temp_setting")
        fan = dps.get("wind_speed") or dps.get("fan_speed") or ""
        if switch:
            parts = ["включён"]
            if mode:
                mode_ru = {"cold": "холод", "hot": "тепло", "wet": "осушение",
                           "wind": "вентилятор", "auto": "авто"}.get(str(mode).lower(), str(mode))
                parts.append(mode_ru)
            if temp_set:
                parts.append(f"{temp_set}°C")
            if fan:
                parts.append(f"вент. {fan}")
            return f"❄️ {name}: {', '.join(parts)}"
        return f"❄️ {name}: выключен"

    # === ТВ ===
    if "тв" in low or "телевизор" in low or "телик" in low:
        switch = dps.get("switch") or dps.get("power")
        return f"📺 {name}: {'включён' if switch else 'выключен'}"

    # === Свет / лампа / розетка ===
    if "свет" in low or "лампа" in low or "розетка" in low:
        switch = dps.get("switch") or dps.get("switch_1")
        power = dps.get("cur_power")
        emoji = "💡" if "свет" in low or "лампа" in low else "🔌"
        state = "включен" if switch else "выключен"
        if power is not None and switch:
            power_w = float(power) / 10 if power > 500 else power
            return f"{emoji} {name}: {state}, {int(power_w)}Вт"
        return f"{emoji} {name}: {state}"

    # === ИК-пульт ===
    if "ик" in low or "пульт" in low or "infrared" in low:
        return f"📡 {name}: онлайн"

    # === Fallback: общий switch ===
    switch = dps.get("switch") or dps.get("switch_1") or dps.get("power")
    if switch is not None:
        return f"🔌 {name}: {'включён' if switch else 'выключен'}"
    return f"🔌 {name}: онлайн"


async def _section_home_status(memory: Any) -> str:
    """Компактная сводка дома с РЕАЛЬНЫМИ показателями по каждому устройству."""
    try:
        from src.config import get_settings
        settings = get_settings()
        lines: list[str] = []

        # Tuya devices — с показателями из DPs
        try:
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(settings)
            if tuya:
                devices = await tuya.list_devices()
                for d in devices:
                    name = (d.get("name") or "").strip()
                    if not name:
                        continue
                    dps = _dps_to_dict(d.get("status", []))
                    line = _format_device_line(name, d.get("online", False), dps)
                    if line:
                        lines.append(line)
        except Exception:
            log.exception("brief_home_tuya_failed")

        # LuxCloud inverter — детальные показатели
        try:
            from src.integrations.luxcloud import LuxCloudClient
            lux = LuxCloudClient.from_settings(settings)
            if lux:
                rt = await lux.runtime()
                if rt.get("online"):
                    soc = rt.get("soc") or rt.get("battery_soc")
                    load = rt.get("load_w") or rt.get("home_w")
                    solar = rt.get("solar_w") or rt.get("pv_w")
                    grid_active = rt.get("grid_active")
                    parts = []
                    if soc is not None:
                        parts.append(f"🔋 {soc}% заряда")
                    if load is not None:
                        parts.append(f"{int(load)}Вт нагрузка")
                    if solar:
                        parts.append(f"☀️ {int(solar)}Вт солнце")
                    parts.append("сеть есть" if grid_active else "нет сети")
                    lines.append(f"⚡ Инвертор: {', '.join(parts)}")
                else:
                    lines.append("⚡ Инвертор: оффлайн")
        except Exception:
            log.exception("brief_home_lux_failed")

        # Vacuum (SmartThings)
        try:
            from src.integrations.smartthings import SmartThingsClient
            st = SmartThingsClient.from_settings(settings)
            if st:
                vac = await st.vacuum_status()
                if vac and vac.get("found"):
                    battery = vac.get("battery")
                    state = vac.get("state", "неизвестно")
                    lines.append(f"🤖 Гоша (пылесос): {state}, батарея {battery}%")
        except Exception:
            log.exception("brief_home_vacuum_failed")

        if not lines:
            return ""
        return "🏠 <b>Умный дом</b>\n" + "\n".join(lines)
    except Exception:
        log.exception("brief_home_status_failed")
        return ""


# ─── Main: compose & send ────────────────────────────────────────────

async def send_morning_brief(
    sender_agent: Any,
    news_agent: Any,
    nanny_agent: Any,
    calendar_agent: Any,
    memory: Any,
) -> None:
    try:
        from src.utils.time import now_kyiv
        date_str = now_kyiv().strftime("%d.%m, %A")
        import asyncio
        news_s, weather_s, baby_s, plans_s, systems_s, vacc_s, sleep_s, home_s = await asyncio.gather(
            _section_news(news_agent, memory),
            _section_weather(),
            _section_baby(nanny_agent, memory),
            _section_plans(calendar_agent, memory),
            _section_systems(memory),
            _section_recent_vaccinations(memory),
            _section_sleep_coach(nanny_agent),
            _section_home_status(memory),
            return_exceptions=False,
        )
        sections = [s for s in (news_s, weather_s, home_s, baby_s, sleep_s, vacc_s, plans_s, systems_s) if s]
        header = f"☀️ <b>Доброе утро!</b> Сводка на {date_str}"
        body = "\n\n".join([header] + sections)
        await sender_agent.send(body)
        log.info("morning_brief_sent", sections=len(sections), sender=getattr(sender_agent, "agent_id", "?"))

        # Если в брифе Дворецкий указал на проблемы и обратился к
        # Прорабу/Няне/др. — выполнить директивы.
        try:
            from src.orchestrator.agent_directives import execute_directives
            peers = getattr(sender_agent, "_peer_agents", None) or {}
            memory_ref = getattr(sender_agent, "_memory", None)
            chat_id = getattr(sender_agent, "_chat_id", 0)
            bots = getattr(sender_agent, "_bots", None)
            if peers and memory_ref and chat_id:
                await execute_directives(
                    text=body, agents=peers, memory=memory_ref,
                    chat_id=chat_id, origin_agent=getattr(sender_agent, "agent_id", None),
                    bot_manager=bots,
                )
        except Exception:
            log.exception("morning_brief_directives_failed")
    except Exception:
        log.exception("morning_brief_failed")


def register_morning_brief_job(
    scheduler,
    sender_agent,
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
        args=[sender_agent, news_agent, nanny_agent, calendar_agent, memory],
        id="morning_brief", replace_existing=True,
    )
    log.info("morning_brief_registered", at=at)
