"""Family HQ Tablet — настенный PWA-хаб.

Serves the tablet UI at /tablet?token=xxx.
Provides API endpoints for state polling and actions:
- GET  /api/tablet/state             — snapshot состояния
- POST /api/tablet/action/scene      — run Tuya scene
- POST /api/tablet/action/socket     — toggle device
- POST /api/tablet/action/baby-event — record diary event
- POST /api/tablet/chat              — send message to agents

Auth: shared token (?token=xxx or header X-Tablet-Token), same as dashboard.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse

import structlog

log = structlog.get_logger()


_TEMPLATE_PATH = Path(__file__).parent / "tablet_template.html"


def _check_token(token: str, expected: str) -> None:
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="invalid token")


async def _build_tablet_state(memory: Any, settings: Any, agents: dict | None = None) -> dict:
    """Собираем состояние для планшета: расширенное относительно dashboard."""
    import asyncio
    from src.utils.time import now_kyiv

    state: dict = {"as_of": now_kyiv().isoformat()}

    # Погода — текущая + прогноз 5 дней
    try:
        from src.integrations.weather import WeatherClient
        w = WeatherClient.from_settings(settings)
        if w:
            cur = await w.current()
            hourly = await w.forecast(hours=120)
            weather = {
                "city": cur.get("city"),
                "temp_c": cur.get("temp_c"),
                "feels_like_c": cur.get("feels_like_c"),
                "description": cur.get("description"),
                "wind_ms": cur.get("wind_ms"),
                "humidity_pct": cur.get("humidity_pct"),
            }
            # 5 дней
            from datetime import datetime
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
            weather["forecast"] = forecast
            state["weather"] = weather
    except Exception:
        log.exception("tablet_weather_failed")

    # Матвей — состояние + время в этом состоянии
    try:
        from src.integrations.baby_state_compute import compute_state_from_diary
        nanny = (agents or {}).get("nanny") if agents else None
        sheets = getattr(nanny, "_sheets", None) if nanny else None
        if sheets:
            bs = await compute_state_from_diary(sheets)
            state["baby"] = bs
    except Exception:
        log.exception("tablet_baby_failed")

    # Датчик детской
    try:
        from src.integrations.tuya import TuyaClient
        tuya = TuyaClient.from_settings(settings)
        if tuya:
            sensor_name = getattr(settings, "baby_room_sensor_name", "детская") or "детская"
            sensor = await tuya.read_sensor(sensor_name)
            if isinstance(sensor, dict) and "readings" in sensor:
                r = sensor.get("readings") or {}
                state["nursery"] = {
                    "temperature": r.get("temperature"),
                    "humidity": r.get("humidity"),
                    "battery": r.get("battery"),
                }
    except Exception:
        log.exception("tablet_nursery_failed")

    # Устройства и сцены Tuya
    try:
        from src.integrations.tuya import TuyaClient
        tuya = TuyaClient.from_settings(settings)
        if tuya:
            devices = await tuya.list_devices()
            dev_out = []
            for d in devices:
                row = {
                    "id": d["id"], "name": d.get("name"),
                    "online": d.get("online"), "category": d.get("category"),
                }
                for s in (d.get("status") or []):
                    code = s.get("code", ""); val = s.get("value")
                    if code == "switch" or code.startswith("switch_"):
                        if "on" not in row:
                            row["on"] = bool(val)
                    if code in ("cur_power", "power"):
                        try:
                            row["cur_power"] = float(val)/10 if val and val > 50 else val
                        except Exception:
                            pass
                    if "temp" in code and "set" not in code and "unit" not in code and "alarm" not in code:
                        try:
                            v = float(val); row["temp"] = v/10 if abs(v) > 80 else v
                        except Exception: pass
                dev_out.append(row)
            state["devices"] = dev_out

            scenes = await tuya.list_scenes()
            state["scenes"] = [
                {"id": s["id"], "name": s["name"], "is_automation": s.get("is_automation", False)}
                for s in scenes if s.get("name")
            ]
    except Exception:
        log.exception("tablet_tuya_failed")

    # Инвертор + автономность
    try:
        from src.integrations.luxcloud import LuxCloudClient
        lux = LuxCloudClient.from_settings(settings)
        if lux:
            rt = await lux.runtime()
            state["inverter"] = {
                "online": rt.get("online"),
                "soc": rt.get("soc") or rt.get("battery_soc"),
                "load_w": rt.get("load_w") or rt.get("home_w"),
                "grid_active": rt.get("grid_active"),
                "solar_w": rt.get("solar_w") or rt.get("pv_w"),
            }
    except Exception:
        log.exception("tablet_lux_failed")

    # Тревога — только если в последние 30 мин был alert-пост от Дозорного
    # (более надёжно чем ActiveAlert таблица которая может иметь stale записи)
    try:
        from datetime import timedelta
        from sqlalchemy import select, func
        from src.db.models import NewsPost
        from src.utils.time import now_kyiv
        cutoff = (now_kyiv() - timedelta(minutes=30)).isoformat()
        async with memory._engine.connect() as conn:
            row = (await conn.execute(
                select(NewsPost).where(NewsPost.is_alert == 1)
                .where(NewsPost.date >= cutoff)
                .order_by(NewsPost.date.desc())
                .limit(1)
            )).first()
        # Активной считаем ТОЛЬКО если alert-пост найден И
        # в тексте нет "отбой"/"відбій" (это end-события)
        if row:
            text = (getattr(row, "text", "") or "").lower()
            is_end = any(w in text for w in ("отбой", "відбій", "видбій", "все ясно", "все спокійно"))
            state["alert"] = {"active": not is_end, "region": row.alert_region, "started_at": row.date}
        else:
            state["alert"] = {"active": False}
    except Exception:
        log.exception("tablet_alert_failed")
        state["alert"] = {"active": False}

    # События сегодня (Google Calendar)
    try:
        from src.integrations.gcalendar import CalendarClient
        if settings.google_service_account_json and settings.calendar_id:
            cal = CalendarClient(settings.google_service_account_json, settings.calendar_id)
            events = await cal.list_upcoming(days_ahead=1)
            today = []
            for e in events[:5]:
                today.append({
                    "title": getattr(e, "title", ""),
                    "when": getattr(e, "start", None).isoformat() if getattr(e, "start", None) else "",
                    "location": getattr(e, "location", ""),
                })
            state["today_events"] = today
    except Exception:
        log.exception("tablet_calendar_failed")

    # Автоматизации
    try:
        from sqlalchemy import select
        from src.db.models import AutomationRule
        async with memory._engine.connect() as conn:
            rows = list(await conn.execute(select(AutomationRule)))
        state["automations"] = [
            {
                "id": r.id, "name": r.name, "enabled": bool(r.enabled),
                "description": r.description or "",
                "fired_count": getattr(r, "fired_count", 0) or 0,
            }
            for r in rows
        ]
    except Exception:
        log.exception("tablet_automations_failed")

    return state


def _load_template() -> str:
    if not _TEMPLATE_PATH.exists():
        return "<html><body><h1>Template missing</h1></body></html>"
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def register_tablet_routes(app: FastAPI, memory: Any, settings: Any, agents_ref: dict) -> None:
    """Регистрируем /tablet и /api/tablet/* в существующем FastAPI-приложении.

    agents_ref — ссылка на словарь agents из main.py (позволяет действиям
    вызывать реальные обработчики агентов и Tuya).
    """
    expected_token = getattr(settings, "dashboard_token", "")

    @app.get("/tablet", response_class=HTMLResponse)
    async def tablet_page(token: str = Query("")):
        _check_token(token, expected_token)
        html = _load_template()
        # Инжектим токен в HTML чтобы JS мог использовать его для API-запросов
        html = html.replace(
            "<script>",
            f"<script>window.TABLET_TOKEN = {json.dumps(token)};",
            1,
        )
        return HTMLResponse(html)

    @app.get("/api/tablet/state")
    async def tablet_state(token: str = Query("")):
        _check_token(token, expected_token)
        state = await _build_tablet_state(memory, settings, agents_ref)
        return JSONResponse(state)

    @app.post("/api/tablet/action/scene")
    async def action_scene(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        scene_id = payload.get("scene_id")
        scene_query = payload.get("query")
        if not scene_id and not scene_query:
            raise HTTPException(400, "scene_id or query required")
        try:
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(settings)
            if not tuya:
                raise HTTPException(503, "Tuya not configured")
            if not scene_id:
                match = await tuya.find_scene(scene_query)
                if not match or match.get("ambiguous"):
                    return {"success": False, "error": "scene_not_found", "match": match}
                scene_id = match["id"]
            result = await tuya.run_scene(scene_id)
            return {"success": bool(result.get("success")), "raw": result.get("raw", "")}
        except HTTPException:
            raise
        except Exception as e:
            log.exception("tablet_scene_run_failed")
            return {"success": False, "error": str(e)[:200]}

    @app.post("/api/tablet/action/socket")
    async def action_socket(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        device = payload.get("device")
        action = payload.get("action", "toggle")  # on/off/toggle
        if not device:
            raise HTTPException(400, "device required")
        try:
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(settings)
            if not tuya:
                raise HTTPException(503, "Tuya not configured")
            result = await tuya.control(device, action)
            return {"success": bool(result.get("success")), "raw": result.get("raw", "")}
        except HTTPException:
            raise
        except Exception as e:
            log.exception("tablet_socket_failed")
            return {"success": False, "error": str(e)[:200]}

    @app.post("/api/tablet/action/baby-event")
    async def action_baby_event(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        kind = payload.get("kind")   # sleep/food/diaper/note/walk
        event = payload.get("event") # «Уснул», «Проснулся», «Грудь Л 150мл» и т.д.
        note = payload.get("note", "")
        if not kind or not event:
            raise HTTPException(400, "kind and event required")
        try:
            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            if not sheets:
                return {"success": False, "error": "sheets not configured"}
            from src.utils.time import now_kyiv
            await sheets.append_baby_diary(
                kind=kind, event=event, time=now_kyiv(),
                author="tablet", note=note,
            )
            return {"success": True}
        except Exception as e:
            log.exception("tablet_baby_event_failed")
            return {"success": False, "error": str(e)[:200]}

    @app.post("/api/tablet/chat")
    async def tablet_chat(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        text = (payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "text required")
        try:
            # Пропускаем через диспетчер как обычное сообщение
            # Возвращаем ответы всех агентов которые обработали
            from src.orchestrator.dispatcher import Dispatcher
            from src.orchestrator.conversation import ConversationContext
            chat_id = settings.hq_chat_id
            context = ConversationContext(memory, chat_id)

            # Простой прямой вызов: обычно диспетчер бы решил кому,
            # но для tablet-chat используем LLM-судью через дворецкого
            # как универсального агента если ничего не подходит.
            responses = []
            butler = agents_ref.get("butler") if agents_ref else None
            if butler:
                resp = await butler.handle(
                    message_text=text,
                    sender_name="tablet",
                    context=context,
                )
                if resp and getattr(resp, "text", None):
                    responses.append({
                        "agent_id": "butler",
                        "text": resp.text,
                    })
            return {"success": True, "responses": responses}
        except Exception as e:
            log.exception("tablet_chat_failed")
            return {"success": False, "error": str(e)[:200]}

    log.info("tablet_routes_registered")
