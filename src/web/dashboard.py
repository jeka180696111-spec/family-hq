"""Web dashboard — read-only view of the family-hq state.

Auth: simple shared token via ?token=… (set via DASHBOARD_TOKEN env).
Runs as a FastAPI app on Railway alongside the bot.

Endpoint:
  GET /dashboard?token=xxx → HTML page
  GET /api/state?token=xxx → JSON snapshot
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select


def _fmt_ago(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        from src.utils.time import KYIV_TZ, now_kyiv
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KYIV_TZ)
        delta = now_kyiv() - dt
        mins = int(delta.total_seconds() // 60)
        if mins < 1:
            return "только что"
        if mins < 60:
            return f"{mins} мин назад"
        h, m = divmod(mins, 60)
        if h < 24:
            return f"{h}ч {m:02d}мин назад" if m else f"{h}ч назад"
        d = h // 24
        return f"{d} дн назад"
    except Exception:
        return iso_str[:16]


def _fmt_duration(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        from src.utils.time import KYIV_TZ, now_kyiv
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KYIV_TZ)
        mins = int((now_kyiv() - dt).total_seconds() // 60)
        if mins < 60:
            return f"{mins}мин"
        h, m = divmod(mins, 60)
        return f"{h}ч {m:02d}мин" if m else f"{h}ч"
    except Exception:
        return ""


def _fmt_clock(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        return iso_str[11:16]
    except Exception:
        return ""


def _check_token(token: str, expected: str) -> None:
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="invalid token")


async def _build_state(memory: Any, settings: Any) -> dict:
    import asyncio
    from src.db.models import (
        ActiveAlert, AutomationRule, BabyState, FamilyFact,
        FuelLog, Parcel, PowerOutage, Trip,
    )
    from src.utils.time import now_kyiv

    state: dict = {"as_of": now_kyiv().isoformat()}

    # Weather (current + 5-day forecast, for Одесса by default)
    try:
        from src.integrations.weather import WeatherClient
        w = WeatherClient.from_settings(settings)
        if w:
            cur = await w.current()
            state["weather"] = {
                "city": cur.get("city"),
                "temp_c": cur.get("temp_c"),
                "feels_like_c": cur.get("feels_like_c"),
                "description": cur.get("description"),
                "wind_ms": cur.get("wind_ms"),
                "humidity_pct": cur.get("humidity_pct"),
            }
            # 5-day forecast: агрегируем hourly в дневные min/max
            try:
                hourly = await w.forecast(hours=120)
                by_day: dict[str, dict] = {}
                for h in hourly:
                    t = (h.get("time") or "")[:10]
                    if not t:
                        continue
                    d = by_day.setdefault(t, {"temps": [], "rain": 0.0, "desc": ""})
                    if h.get("temp_c") is not None:
                        d["temps"].append(h["temp_c"])
                    d["rain"] += h.get("rain_mm") or 0
                    if not d["desc"]:
                        d["desc"] = h.get("description") or ""
                forecast = []
                for day, agg in sorted(by_day.items())[:5]:
                    if not agg["temps"]:
                        continue
                    forecast.append({
                        "date": day,
                        "min": round(min(agg["temps"])),
                        "max": round(max(agg["temps"])),
                        "rain": round(agg["rain"], 1),
                        "desc": agg["desc"],
                    })
                state["weather"]["forecast"] = forecast
            except Exception:
                pass
    except Exception:
        pass

    # Smart-home devices (Tuya) — full list with on/off + power
    try:
        from src.integrations.tuya import TuyaClient
        tuya = TuyaClient.from_settings(settings)
        if tuya:
            devices = []
            for attempt in range(2):
                try:
                    devices = await tuya.list_devices()
                    if devices:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.8)
            sh = []
            for d in devices:
                row = {
                    "name": d.get("name"), "category": d.get("category"),
                    "online": d.get("online"), "id": d.get("id"),
                }
                seen_switch = False
                for s in (d.get("status") or []):
                    code = s.get("code", "")
                    val = s.get("value")
                    # First switch code wins — multiple may exist (switch_1, switch_led)
                    if (not seen_switch) and (code == "switch" or code.startswith("switch_")) \
                            and not code.startswith("switch_led"):
                        row["on"] = bool(val)
                        seen_switch = True
                    if code in ("cur_power", "power"):
                        # Tuya reports cur_power in 0.1W units
                        try:
                            row["cur_power"] = float(val) / 10 if val and val > 50 else val
                        except Exception:
                            row["cur_power"] = val
                    if code == "cur_voltage":
                        try:
                            row["cur_voltage"] = float(val) / 10 if val else val
                        except Exception:
                            row["cur_voltage"] = val
                    if (("temp" in code or "temperature" in code)
                            and "unit" not in code and "set" not in code
                            and "calib" not in code and "alarm" not in code):
                        try:
                            fv = float(val) if val is not None else None
                            # Tuya often reports temp in 0.1°C units (e.g. 237 = 23.7°C)
                            if fv is not None and abs(fv) > 80:
                                fv = fv / 10
                            row["temp"] = fv
                        except Exception:
                            row["temp"] = val
                    if "humi" in code and "set" not in code and "calib" not in code:
                        row["humidity"] = val
                    if "battery" in code and "set" not in code:
                        row["battery"] = val
                sh.append(row)
            state["smart_home"] = sh

            # Nursery sensor = the first sensor-like device with temperature
            nursery_dev = next(
                (d for d in sh
                 if d.get("temp") is not None or d.get("humidity") is not None),
                None,
            )
            if nursery_dev:
                state["nursery"] = {
                    "temperature": f"{nursery_dev.get('temp')}°C" if nursery_dev.get("temp") is not None else "",
                    "humidity": f"{nursery_dev.get('humidity')}%" if nursery_dev.get("humidity") is not None else "",
                    "battery": f"{nursery_dev.get('battery')}%" if nursery_dev.get("battery") is not None else "",
                }
    except Exception:
        pass

    # Inverter / outage
    try:
        from src.integrations.luxcloud import LuxCloudClient
        lux = LuxCloudClient.from_settings(settings)
        if lux:
            rt = await lux.runtime()
            state["inverter"] = {
                "battery_pct": rt.get("battery_pct"),
                "battery_charge_w": rt.get("battery_charge_w"),
                "battery_discharge_w": rt.get("battery_discharge_w"),
                "grid_import_w": rt.get("grid_import_w"),
                "home_consumption_w": rt.get("home_consumption_w"),
                "online": rt.get("online"),
                "status": rt.get("status"),
                "active_codes": rt.get("active_codes"),
            }
    except Exception:
        state["inverter"] = {"error": "unreachable"}

    # Active power outage — read from DB so the dashboard reflects what
    # GridWatcher knows, not what the inverter currently reports.
    try:
        from sqlalchemy import select
        from src.db.models import PowerOutage
        from src.utils.time import now_kyiv
        from datetime import datetime as _dt
        async with memory._engine.connect() as conn:
            open_row = (await conn.execute(
                select(PowerOutage).where(PowerOutage.ended_at.is_(None))
                .order_by(PowerOutage.id.desc()).limit(1)
            )).first()
        if open_row:
            started = _dt.fromisoformat(open_row.started_at)
            elapsed_min = int((now_kyiv() - started).total_seconds() / 60)
            state["outage"] = {
                "active": True,
                "started_at": open_row.started_at,
                "elapsed_min": elapsed_min,
                "notes": open_row.notes or "",
            }
        else:
            state["outage"] = {"active": False}
    except Exception:
        state["outage"] = {"active": False, "error": "db_unreachable"}

    # Nursery sensor (Tuya is flaky — 2 attempts)
    try:
        import asyncio
        from src.integrations.tuya import TuyaClient
        tuya = TuyaClient.from_settings(settings)
        if tuya:
            reading = None
            for attempt in range(2):
                try:
                    reading = await tuya.read_sensor("детская")
                    if reading and "error" not in reading:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.8)
            if reading and "error" not in reading:
                state["nursery"] = reading.get("readings", {})
    except Exception:
        pass

    async with memory._engine.connect() as conn:
        outage = (await conn.execute(
            select(PowerOutage).where(PowerOutage.ended_at.is_(None)).limit(1)
        )).first()
        state["power_off"] = outage is not None

        alerts = list(await conn.execute(select(ActiveAlert)))
        state["alerts"] = [{"region": a.region} for a in alerts]

        baby = (await conn.execute(select(BabyState).where(BabyState.id == 1))).first()
        baby_state: dict = {}
        if baby:
            baby_state = {
                "sleeping_since": baby.sleeping_since,
                "awake_since": baby.awake_since,
                "last_feed_at": baby.last_feed_at,
                "last_diaper_at": baby.last_diaper_at,
                "walking_since": baby.walking_since,
                "walk_ended_at": baby.walk_ended_at,
            }

        trips =list(await conn.execute(
            select(Trip).where(Trip.status.in_(("planned", "active")))
            .order_by(Trip.depart_at.asc()).limit(5)
        ))
        state["trips"] = [
            {"id": t.id, "from": t.origin, "to": t.destination,
             "depart_at": t.depart_at, "distance_km": t.distance_km,
             "duration_min": t.duration_min, "fuel_l": t.fuel_estimate_l,
             "status": t.status}
            for t in trips
        ]

        rules = list(await conn.execute(
            select(AutomationRule).where(AutomationRule.enabled == 1)
        ))
        state["automations"] = [
            {"name": r.name, "cooldown": r.cooldown_min,
             "fires": r.fired_count, "last": r.last_fired_at}
            for r in rules
        ]

        fuel = list(await conn.execute(
            select(FuelLog).order_by(FuelLog.id.desc()).limit(5)
        ))
        state["recent_fuel"] = [
            {"when": f.created_at, "station": f.station,
             "liters": f.liters, "total": f.total_uah, "odo": f.odometer_km}
            for f in fuel
        ]

        parcels = list(await conn.execute(
            select(Parcel).where(Parcel.delivered_at.is_(None))
        ))
        state["parcels"] = [
            {"ttn": p.ttn, "title": p.title, "status": p.status,
             "checked_at": p.last_checked_at}
            for p in parcels
        ]

        wiki = list(await conn.execute(select(FamilyFact)))
        state["wiki"] = [
            {"member": w.member, "key": w.key, "value": w.value}
            for w in wiki
        ]

    if baby_state:
        state["baby"] = baby_state

    # Active agents (from DB seed) — show health/status
    try:
        from src.db.models import Agent as AgentModel
        async with memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(AgentModel).where(AgentModel.status == "active")
            ))
        state["agents"] = [
            {"id": a.agent_id, "name": a.name, "emoji": a.emoji,
             "zone": a.zone, "verbosity": a.verbosity}
            for a in rows
        ]
    except Exception:
        pass

    # Upcoming events from Google Calendar (next 7 days)
    try:
        from src.integrations.gcalendar import CalendarClient
        if settings.google_service_account_json and settings.calendar_id:
            cal = CalendarClient(settings.google_service_account_json, settings.calendar_id)
            events = await cal.list_upcoming(days=7)
            state["upcoming"] = [
                {"title": getattr(e, "title", ""),
                 "when": getattr(e, "start", None).isoformat() if getattr(e, "start", None) else "",
                 "location": getattr(e, "location", "")}
                for e in events[:10]
            ]
    except Exception:
        pass

    # AI provider stats
    try:
        from src.integrations.claude_client import get_ai_stats
        state["ai"] = get_ai_stats()
        state["ai"]["gemini_configured"] = bool(getattr(settings, "gemini_api_key", ""))
    except Exception:
        pass

    return state


def _render_html(state: dict) -> str:
    """Render a minimal but readable HTML view of the state."""
    def card(title: str, body: str) -> str:
        return f'<section class="card"><h2>{title}</h2>{body}</section>'

    inv = state.get("inverter") or {}
    outage = state.get("outage") or {}
    outage_banner = ""
    if outage.get("active"):
        mins = outage.get("elapsed_min") or 0
        h, m = divmod(mins, 60)
        elapsed = f"{h}ч {m}мин" if h else f"{m}мин"
        outage_banner = (
            f'<p style="background:#7c1d1d;color:#fff;padding:8px 12px;'
            f'border-radius:6px;margin:0 0 8px 0;font-weight:600;">'
            f"⚡ СВЕТА НЕТ — {elapsed}</p>"
        )
    discharge = inv.get("battery_discharge_w") or 0
    on_battery = discharge > 30
    grid_label = (
        "🔌 на батарее" if on_battery
        else f"⚡ сеть: импорт <b>{inv.get('grid_import_w', 0)}Вт</b>"
    )
    inv_body = (
        f"<p>🔋 Батарея: <b>{inv.get('battery_pct', '?')}%</b>"
        + (f" (разряд {discharge}Вт)" if on_battery else "")
        + f"<br>{grid_label}<br>"
        f"🏠 Дом: <b>{inv.get('home_consumption_w', 0)}Вт</b></p>"
    ) if "battery_pct" in inv else "<p>—</p>"
    inv_html = outage_banner + inv_body

    nursery = state.get("nursery") or {}
    nursery_html = (
        f"<p>🌡 {nursery.get('temperature', '?')}<br>"
        f"💧 {nursery.get('humidity', '?')}<br>"
        f"🔋 датчик {nursery.get('battery', '?')}</p>"
    ) if nursery else "<p>—</p>"

    baby = state.get("baby") or {}
    # Current activity logic: walk > sleep > awake
    activity_html = ""
    sleeping = baby.get("sleeping_since")
    walking = baby.get("walking_since")
    awake = baby.get("awake_since")
    if walking and not baby.get("walk_ended_at"):
        activity_html = (
            f"🚶 <b>На прогулке</b> · {_fmt_duration(walking)}<br>"
            f"⏰ Вышли в {_fmt_clock(walking)}"
        )
    elif sleeping:
        activity_html = (
            f"😴 <b>Спит</b> · {_fmt_duration(sleeping)}<br>"
            f"⏰ Уснул в {_fmt_clock(sleeping)}"
        )
    elif awake:
        activity_html = (
            f"🌅 <b>Бодрствует</b> · {_fmt_duration(awake)}<br>"
            f"⏰ Проснулся в {_fmt_clock(awake)}"
        )
    else:
        activity_html = "<i>Няня ещё ничего не записала</i>"

    feed_ago = _fmt_ago(baby.get("last_feed_at"))
    diaper_ago = _fmt_ago(baby.get("last_diaper_at"))
    baby_html = (
        f"<p>{activity_html}</p>"
        f"<p>🍼 Кушал: <b>{feed_ago}</b><br>"
        f"💧 Подгузник: <b>{diaper_ago}</b></p>"
    )

    trips_html = "<ul>" + "".join(
        f"<li>{t['from']} → {t['to']} ({t['depart_at']}, {t.get('distance_km', '?')}км)</li>"
        for t in state.get("trips", [])
    ) + "</ul>" if state.get("trips") else "<p>Поездок нет</p>"

    auto_html = "<ul>" + "".join(
        f"<li><b>{a['name']}</b> — сработало {a['fires']} раз</li>"
        for a in state.get("automations", [])
    ) + "</ul>" if state.get("automations") else "<p>Правил нет</p>"

    parcels_html = "<ul>" + "".join(
        f"<li>📦 {p.get('title') or p['ttn']} — {p.get('status') or '?'}</li>"
        for p in state.get("parcels", [])
    ) + "</ul>" if state.get("parcels") else "<p>Активных нет</p>"

    wiki_html = "<ul>" + "".join(
        f"<li><b>{w['member']}</b> · {w['key']}: {w['value']}</li>"
        for w in state.get("wiki", [])
    ) + "</ul>" if state.get("wiki") else "<p>Пусто</p>"

    # AI provider card
    ai = state.get("ai") or {}
    if ai:
        prov = ai.get("current_provider", "claude")
        icon = "🧠" if prov == "claude" else "🌀"
        label = "Claude" if prov == "claude" else "Gemini"
        ai_html = (
            f"<p>{icon} <b>{label}</b> сейчас отвечает<br>"
            f"Claude: {ai.get('claude_count', 0)} ✓ / {ai.get('claude_fail_count', 0)} ✗<br>"
            f"Gemini: {ai.get('gemini_count', 0)} ✓ / {ai.get('gemini_fail_count', 0)} ✗<br>"
            f"Fallback: {'✅ готов' if ai.get('gemini_configured') else '⚠️ нет ключа'}</p>"
        )
    else:
        ai_html = "<p>—</p>"

    # Weather card
    w = state.get("weather") or {}
    if w.get("temp_c") is not None:
        weather_html = (
            f"<p>📍 {w.get('city', 'Одесса')}<br>"
            f"🌡 <b>{w['temp_c']:+.0f}°</b> (ощущается {w.get('feels_like_c', w['temp_c']):+.0f}°)<br>"
            f"☁️ {w.get('description') or '—'}<br>"
            f"💨 ветер {w.get('wind_ms', 0)} м/с · 💧 {w.get('humidity_pct', '?')}%</p>"
        )
    else:
        weather_html = "<p>—</p>"

    # Alerts card
    alerts = state.get("alerts") or []
    if alerts:
        alerts_html = "🚨 <b>Активна:</b><br>" + "<br>".join(
            f"• {a['region']}" for a in alerts
        )
    else:
        alerts_html = "<p>✅ Тревог нет</p>"

    # Smart-home devices
    sh = state.get("smart_home") or []
    if sh:
        rows = []
        for d in sh:
            online = "🟢" if d.get("online") else "⚪"
            sw = ""
            if d.get("on") is True:
                sw = "🔛 <b>ВКЛ</b>"
            elif d.get("on") is False:
                sw = "🔘 выкл"
            extra = []
            if d.get("temp") is not None:
                t = d["temp"] / 10 if d["temp"] > 100 else d["temp"]
                extra.append(f"🌡 {t}°")
            if d.get("humidity") is not None:
                extra.append(f"💧 {d['humidity']}%")
            if d.get("battery") is not None:
                extra.append(f"🔋 {d['battery']}%")
            if d.get("cur_power") not in (None, 0):
                extra.append(f"⚡ {d['cur_power']}Вт")
            extras = " · ".join(extra)
            rows.append(
                f"<li>{online} <b>{d.get('name') or '?'}</b> {sw}"
                + (f" · {extras}" if extras else "") + "</li>"
            )
        smart_home_html = "<ul>" + "".join(rows) + "</ul>"
    else:
        smart_home_html = "<p>—</p>"

    # Agents
    agents = state.get("agents") or []
    if agents:
        agents_html = "<ul>" + "".join(
            f"<li>{a['emoji']} <b>{a['name']}</b> · {a['zone']} · {a['verbosity']}</li>"
            for a in agents
        ) + "</ul>"
    else:
        agents_html = "<p>—</p>"

    # Upcoming events
    upcoming = state.get("upcoming") or []
    if upcoming:
        upcoming_html = "<ul>" + "".join(
            f"<li>{e['when'][:16].replace('T', ' ')} · <b>{e['title']}</b>"
            + (f" · {e['location']}" if e.get('location') else "") + "</li>"
            for e in upcoming
        ) + "</ul>"
    else:
        upcoming_html = "<p>Свободно</p>"

    # Прогноз погоды на 5 дней в виде плиток
    forecast_html = ""
    forecast = (w.get("forecast") or []) if isinstance(w, dict) else []
    if forecast:
        weekday_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
        tiles = []
        for f in forecast:
            try:
                d = datetime.fromisoformat(f["date"])
                wd = weekday_ru[d.weekday()]
                dd = d.strftime("%d.%m")
            except Exception:
                wd, dd = f["date"], ""
            icon = "🌧" if f["rain"] > 0.5 else ("☁️" if "облач" in (f.get("desc") or "").lower() else "☀️")
            tiles.append(
                f'<div class="fc-day"><div class="fc-day-title">{wd}</div>'
                f'<div class="fc-day-date">{dd}</div>'
                f'<div class="fc-day-icon">{icon}</div>'
                f'<div class="fc-day-temp"><span class="fc-max">{f["max"]:+.0f}°</span>'
                f'<span class="fc-min">{f["min"]:+.0f}°</span></div>'
                f'<div class="fc-day-rain">💧 {f["rain"]}мм</div></div>'
            )
        forecast_html = f'<div class="forecast">{"".join(tiles)}</div>'

    # Круговой индикатор заряда инвертора
    battery_gauge = ""
    if inv.get("battery_pct") is not None:
        pct = int(inv["battery_pct"])
        color = "#22c55e" if pct >= 50 else ("#eab308" if pct >= 20 else "#ef4444")
        battery_gauge = f'''
        <div class="gauge">
          <svg viewBox="0 0 120 120" width="120" height="120">
            <circle cx="60" cy="60" r="52" fill="none" stroke="#1f2937" stroke-width="12"/>
            <circle cx="60" cy="60" r="52" fill="none" stroke="{color}" stroke-width="12"
                    stroke-dasharray="{pct * 3.27:.1f} 327" transform="rotate(-90 60 60)"
                    stroke-linecap="round"/>
            <text x="60" y="68" text-anchor="middle" fill="#e6edf3" font-size="26" font-weight="700">{pct}%</text>
          </svg>
        </div>
        '''

    # Clock / as_of
    as_of = state.get("as_of", "")
    now_display = ""
    try:
        d = datetime.fromisoformat(as_of)
        now_display = d.strftime("%H:%M")
    except Exception:
        pass

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Family HQ · Дашборд</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
    background-attachment: fixed;
    color: #e2e8f0;
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px 16px;
    min-height: 100vh;
  }}
  .header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 24px; padding: 16px 20px;
    background: rgba(30, 41, 59, 0.6);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 20px;
  }}
  .header h1 {{
    margin: 0; font-size: 24px; font-weight: 700;
    background: linear-gradient(90deg, #a78bfa, #60a5fa, #34d399);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }}
  .header .clock {{
    font-size: 28px; font-weight: 600; color: #f1f5f9;
    font-variant-numeric: tabular-nums;
  }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px; margin-bottom: 16px;
  }}
  .card {{
    background: rgba(30, 41, 59, 0.55);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 18px;
    padding: 20px;
    transition: transform 0.2s, border 0.2s;
  }}
  .card:hover {{ transform: translateY(-2px); border-color: rgba(148, 163, 184, 0.3); }}
  .card h2 {{
    margin: 0 0 12px; font-size: 14px; font-weight: 600;
    color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .card p {{ margin: 4px 0; font-size: 15px; line-height: 1.6; }}
  .card b {{ color: #f1f5f9; }}
  .big {{ font-size: 32px; font-weight: 700; color: #f1f5f9; margin: 8px 0; }}
  .accent {{ color: #a78bfa; }}
  ul {{ margin: 6px 0; padding-left: 20px; list-style: none; }}
  ul li {{ margin: 6px 0; padding-left: 8px; border-left: 2px solid rgba(148, 163, 184, 0.3); }}

  .alert-banner {{
    background: linear-gradient(90deg, #dc2626, #ea580c);
    color: white; padding: 12px 20px; border-radius: 14px;
    margin-bottom: 16px; font-weight: 600; text-align: center;
    box-shadow: 0 4px 20px rgba(220, 38, 38, 0.4);
  }}

  .forecast {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 12px; }}
  @media (max-width: 500px) {{ .forecast {{ grid-template-columns: repeat(3, 1fr); }} }}
  .fc-day {{
    background: rgba(15, 23, 42, 0.5);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 12px; padding: 10px 4px; text-align: center;
  }}
  .fc-day-title {{ font-size: 12px; color: #94a3b8; font-weight: 600; }}
  .fc-day-date {{ font-size: 10px; color: #64748b; }}
  .fc-day-icon {{ font-size: 24px; margin: 6px 0; }}
  .fc-day-temp {{ font-size: 13px; }}
  .fc-max {{ color: #f1f5f9; font-weight: 700; }}
  .fc-min {{ color: #64748b; margin-left: 4px; }}
  .fc-day-rain {{ font-size: 10px; color: #60a5fa; margin-top: 4px; }}

  .gauge {{ display: flex; justify-content: center; align-items: center; margin: 8px 0; }}

  .device-list {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 8px; margin-top: 8px;
  }}
  .device-item {{
    background: rgba(15, 23, 42, 0.5);
    padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(148, 163, 184, 0.1);
    display: flex; justify-content: space-between; align-items: center;
    font-size: 14px;
  }}
  .device-item .dev-name {{ font-weight: 600; color: #f1f5f9; }}
  .device-item .dev-status {{ font-size: 12px; color: #94a3b8; }}
  .dev-on {{ color: #22c55e; }}
  .dev-off {{ color: #64748b; }}

  .status-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
  .dot-green {{ background: #22c55e; box-shadow: 0 0 6px #22c55e; }}
  .dot-red {{ background: #ef4444; box-shadow: 0 0 6px #ef4444; }}
  .dot-gray {{ background: #64748b; }}

  .footer {{
    text-align: center; margin-top: 24px; padding: 16px;
    color: #64748b; font-size: 12px;
  }}
  .footer a {{ color: #60a5fa; text-decoration: none; }}

  @keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.6; }}
  }}
  .pulsing {{ animation: pulse 2s infinite; }}
</style></head><body>

<div class="header">
  <h1>🏠 Family HQ</h1>
  <div class="clock">{now_display}</div>
</div>

{outage_banner}

<div class="grid">

  <div class="card">
    <h2>🌤 Погода</h2>
    {weather_html}
    {forecast_html}
  </div>

  <div class="card">
    <h2>☀️ Инвертор</h2>
    {battery_gauge}
    <p>{grid_label}<br>🏠 Дом: <b>{inv.get('home_consumption_w', 0)}Вт</b></p>
  </div>

  <div class="card">
    <h2>👶 Матвей</h2>
    <p>{activity_html}</p>
    <p>🍼 Кушал: <b>{feed_ago}</b><br>💧 Подгузник: <b>{diaper_ago}</b></p>
  </div>

  <div class="card">
    <h2>🌡 Детская</h2>
    {nursery_html}
  </div>

  <div class="card">
    <h2>🚨 Тревога</h2>
    {alerts_html}
  </div>

  <div class="card">
    <h2>🧠 AI</h2>
    {ai_html}
  </div>

</div>

<div class="card" style="margin-bottom:16px">
  <h2>🏠 Умный дом</h2>
  {smart_home_html}
</div>

<div class="grid">
  <div class="card">
    <h2>📅 Ближайшие события</h2>
    {upcoming_html}
  </div>
  <div class="card">
    <h2>🤖 Автоматизации</h2>
    {auto_html}
  </div>
  <div class="card">
    <h2>🛣 Поездки</h2>
    {trips_html}
  </div>
  <div class="card">
    <h2>📦 Посылки</h2>
    {parcels_html}
  </div>
</div>

<div class="card">
  <h2>👥 Агенты</h2>
  {agents_html}
</div>

<div class="footer">
  Обновлено: {as_of[:19].replace('T', ' ')} · <a href="?json=1&token=">JSON</a>
</div>

</body></html>"""


def build_app(memory: Any, settings: Any) -> FastAPI:
    app = FastAPI(title="Family HQ Dashboard")
    expected_token = getattr(settings, "dashboard_token", "")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(token: str = Query("")):
        _check_token(token, expected_token)
        state = await _build_state(memory, settings)
        return HTMLResponse(_render_html(state))

    @app.get("/api/state")
    async def api_state(token: str = Query("")):
        _check_token(token, expected_token)
        state = await _build_state(memory, settings)
        return JSONResponse(state)

    return app


async def start_dashboard_server(memory: Any, settings: Any, port: int) -> None:
    """Start uvicorn in the same event loop."""
    import structlog
    log = structlog.get_logger()
    try:
        import uvicorn
    except Exception:
        log.warning("dashboard_uvicorn_missing")
        return
    app = build_app(memory, settings)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    log.info("dashboard_starting", port=port)
    import asyncio
    asyncio.create_task(server.serve())
