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
    from src.db.models import (
        ActiveAlert, AutomationRule, BabyState, FamilyFact,
        FuelLog, Parcel, PowerOutage, Trip,
    )
    from src.utils.time import now_kyiv

    state: dict = {"as_of": now_kyiv().isoformat()}

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

    # Overlay baby state computed live from the Дневник sheet (source of
    # truth — entries may come from a different bot or manual edits).
    try:
        from src.config import get_settings
        from src.integrations.baby_state_compute import compute_state_from_diary
        from src.integrations.sheets import SheetsClient
        s = get_settings()
        if s.google_service_account_json and s.sheet_baby_id:
            sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")
            fresh = await compute_state_from_diary(sheets)
            if fresh:
                baby_state.update({k: v for k, v in fresh.items() if v})
    except Exception:
        import structlog
        structlog.get_logger().exception("dashboard_diary_state_failed")

    if baby_state:
        state["baby"] = baby_state

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
  {card("👶 Детская", nursery_html)}
  {card("🤱 Матвей", baby_html)}
  {card("🛣 Поездки", trips_html)}
  {card("🤖 Автоматизации", auto_html)}
  {card("📦 Посылки", parcels_html)}
</div>
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
