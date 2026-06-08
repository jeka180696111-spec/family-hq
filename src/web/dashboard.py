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

    # Weather (current, for Одесса by default)
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
                    if "temp" in code and "current" in code:
                        try:
                            row["temp"] = float(val) / 10 if val and val > 100 else val
                        except Exception:
                            row["temp"] = val
                    if "humi" in code:
                        row["humidity"] = val
                    if "battery" in code:
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
            }
    except Exception:
        state["inverter"] = {"error": "unreachable"}

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

    return state


def _render_html(state: dict) -> str:
    """Render a minimal but readable HTML view of the state."""
    def card(title: str, body: str) -> str:
        return f'<section class="card"><h2>{title}</h2>{body}</section>'

    inv = state.get("inverter") or {}
    inv_html = (
        f"<p>🔋 Батарея: <b>{inv.get('battery_pct', '?')}%</b><br>"
        f"⚡ Сеть: импорт <b>{inv.get('grid_import_w', 0)}Вт</b><br>"
        f"🏠 Дом: <b>{inv.get('home_consumption_w', 0)}Вт</b></p>"
    ) if "battery_pct" in inv else "<p>—</p>"

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

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Family HQ · Дашборд</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background:#0d1117;
         color:#e6edf3; max-width:880px; margin:24px auto; padding:0 16px; }}
  h1 {{ font-size:22px; }}
  h2 {{ font-size:16px; margin:0 0 8px; color:#58a6ff; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
           padding:14px 16px; margin:12px 0; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  @media (max-width:600px) {{ .grid {{ grid-template-columns:1fr; }} }}
  ul {{ margin:6px 0; padding-left:20px; }}
  li {{ margin:3px 0; }}
  .footer {{ color:#7d8590; font-size:12px; margin-top:24px; }}
</style></head><body>
<h1>Family HQ · Дашборд</h1>
<div class="grid">
  {card("☀️ Инвертор", inv_html)}
  {card("🚨 Тревога", alerts_html)}
  {card("🌤 Погода", weather_html)}
  {card("👶 Детская", nursery_html)}
  {card("🤱 Матвей", baby_html)}
  {card("🛣 Поездки", trips_html)}
  {card("🤖 Автоматизации", auto_html)}
  {card("📦 Посылки", parcels_html)}
</div>
{card("🏠 Умный дом", smart_home_html)}
{card("📅 События (7 дней)", upcoming_html)}
{card("👥 Агенты", agents_html)}
{card("🧠 Family Wiki", wiki_html)}
<div class="footer">Обновлено: {state.get('as_of', '')[:19]}. JSON: <a href="?json=1">/api/state</a></div>
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
