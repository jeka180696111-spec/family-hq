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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import structlog

log = structlog.get_logger()


_TEMPLATE_PATH = Path(__file__).parent / "tablet_template.html"
_STATIC_DIR = Path(__file__).parent / "static"


def _check_token(token: str, expected: str) -> None:
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="invalid token")


# _build_tablet_state() runs on every /api/tablet/state hit — every 8s while
# the tablet is open, all day. Tuya/LuxCloud/SmartThings clients were being
# constructed fresh via .from_settings() on every single call, which meant:
# a brand new (unauthenticated) instance each time, so Tuya's own token +
# 60s/300s device/scene caches never actually persisted between polls (they
# live on the instance, and the instance never survived past one call), and
# LuxCloud had to do a full login handshake every 8 seconds instead of once.
# That's the real reason Tuya's quota drained so fast even after removing
# force_refresh, and why LuxCloud occasionally missed the 5s per-call budget
# on a cold connection + login round-trip. One process-lifetime instance per
# integration, reused across every poll, fixes both at the root.
_shared_clients: dict[str, Any] = {}


def _cached_client(key: str, factory):
    if key not in _shared_clients:
        _shared_clients[key] = factory()
    return _shared_clients[key]


async def _build_tablet_state(memory: Any, settings: Any, agents: dict | None = None) -> dict:
    """Собираем состояние для планшета: расширенное относительно dashboard."""
    import asyncio
    from src.utils.time import now_kyiv

    state: dict = {"as_of": now_kyiv().isoformat()}

    # Матвей — базовые факты (имя + дата рождения) для точного возраста в UI
    try:
        from src.utils.baby import MATVEY_BIRTH_DATE, matvey_age_short
        from src.scheduler.sleep_predictor import _expected_wake_window_min
        from datetime import date
        age_days = (date.today() - MATVEY_BIRTH_DATE).days
        age_months = age_days / 30.4375
        wake_min = _expected_wake_window_min(age_months)
        state["child"] = {
            "name": "Матвей",
            "birth_date": MATVEY_BIRTH_DATE.isoformat(),
            "age_label": matvey_age_short(),
            "age_months": round(age_months, 1),
            # Возрастное окно бодрствования (Weissbluth/AAP). Меняется
            # по мере роста Матвея — UI использует чтобы не хардкодить.
            "wake_window_min": wake_min,
            # За 15 мин до окончания окна — уже «Устал»
            "tired_at_min": max(30, wake_min - 15),
        }
    except Exception:
        log.exception("tablet_child_facts_failed")

    # Home state — «Уехали из дома» / «Я дома». Используется движком
    # автоматизаций (family_away / family_home) и кнопкой в шапке.
    try:
        raw = await memory.get_agent_setting("tablet", "home_state", "home")
        state["home_state"] = raw or "home"
    except Exception:
        state["home_state"] = "home"

    # Погода — текущая + прогноз 5 дней
    try:
        from src.integrations.weather import WeatherClient
        w = WeatherClient.from_settings(settings)
        if w:
            cur = await asyncio.wait_for(w.current(), timeout=5.0)
            hourly = await asyncio.wait_for(w.forecast(hours=120), timeout=5.0)
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

    # Датчик детской — сначала пробуем по настроенному имени,
    # затем fallback на ЛЮБОЕ устройство содержащее датчик температуры
    try:
        from src.integrations.tuya import TuyaClient
        tuya = _cached_client("tuya", lambda: TuyaClient.from_settings(settings))
        if tuya:
            # Явный короткий таймаут на КАЖДЫЙ вызов Tuya: у клиента и так
            # свои 15с на HTTP-запрос, а вся _build_tablet_state ограничена
            # 20с суммарно — если Tuya сейчас лежит (квота и т.п.), она может
            # «думать» все 15с перед ошибкой и не оставить времени на секции
            # ниже (инвертор, календарь, автоматизации), которые от Tuya
            # никак не зависят. 5с достаточно для нормального ответа Tuya.
            sensor_name = getattr(settings, "baby_room_sensor_name", "детская") or "детская"
            sensor = await asyncio.wait_for(tuya.read_sensor(sensor_name), timeout=5.0)
            got = isinstance(sensor, dict) and "readings" in sensor and sensor.get("readings")
            if not got:
                # Fallback: ищем среди устройств первое с temperature/va_temperature.
                # Без force_refresh — план­шет опрашивает состояние каждые 8с, а тут
                # и без того есть 60-секундный кэш в клиенте; форсировать его каждый
                # раз означало бы в ~7 раз больше запросов к Tuya, чем нужно.
                devices = await asyncio.wait_for(tuya.list_devices(), timeout=5.0)
                for d in devices:
                    for s in (d.get("status") or []):
                        code = s.get("code", "")
                        if code in ("va_temperature", "temp_current", "temperature"):
                            sensor = await asyncio.wait_for(
                                tuya.read_sensor(d.get("name", "")), timeout=5.0,
                            )
                            got = isinstance(sensor, dict) and "readings" in sensor and sensor.get("readings")
                            if got:
                                break
                    if got:
                        break
            if got:
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
        tuya = _cached_client("tuya", lambda: TuyaClient.from_settings(settings))
        if tuya:
            # Без force_refresh — см. комментарий у датчика детской выше:
            # 60-секундный кэш клиента более чем достаточен для опроса раз
            # в 8с, а форсировать его — платить лимитом Tuya без реальной
            # нужды (обновление раз в минуту незаметно на настенном экране).
            # Короткий локальный таймаут — см. комментарий выше про 15с/20с.
            devices = await asyncio.wait_for(tuya.list_devices(), timeout=5.0)
            dev_out = []
            for d in devices:
                row = {
                    "id": d["id"], "name": d.get("name"),
                    "online": d.get("online"), "category": d.get("category"),
                }
                for s in (d.get("status") or []):
                    code = s.get("code") or ""; val = s.get("value")
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
                    if "humi" in code or code == "va_humidity":
                        try:
                            v = float(val); row["humi"] = v/10 if v > 100 else v
                        except Exception: pass
                    if code == "battery_percentage" or code == "battery":
                        try:
                            row["battery"] = int(val)
                        except Exception: pass
                dev_out.append(row)
            state["devices"] = dev_out

            scenes = await asyncio.wait_for(tuya.list_scenes(), timeout=5.0)
            state["scenes"] = [
                {"id": s["id"], "name": s["name"], "is_automation": s.get("is_automation", False)}
                for s in scenes if s.get("name")
            ]
    except Exception:
        log.exception("tablet_tuya_failed")


    # SmartThings — робот-пылесос (Гоша / robot / любое имя)
    try:
        from src.integrations.smartthings import SmartThingsClient
        st = _cached_client("smartthings", lambda: SmartThingsClient.from_settings(settings, memory=memory))
        if st:
            devices_st = await asyncio.wait_for(st.list_devices(), timeout=5.0)
            log.info("tablet_smartthings_devices",
                     count=len(devices_st),
                     names=[d.get("name") for d in devices_st][:20])
            vac = (st.find_vacuum(devices_st, "гоша")
                   or st.find_vacuum(devices_st, "robot")
                   or st.find_vacuum(devices_st))
            if vac:
                summary = await st.vacuum_summary(vac)
                movement = str(summary.get("movement") or "").lower()  # cleaning|homing|idle|charging
                mode = str(summary.get("mode") or "").lower()
                battery = summary.get("battery")
                RU_STATE = {
                    "cleaning": "убирает",
                    "homing":   "на базу",
                    "charging": "заряжается",
                    "idle":     "готов",
                    "paused":   "пауза",
                }
                state_ru = RU_STATE.get(movement, movement or mode or "готов")
                extra_parts = [state_ru]
                if battery is not None:
                    extra_parts.append(f"батарея {battery}%")
                state.setdefault("devices", []).append({
                    "id": vac.get("id"),
                    "name": "Гоша (пылесос)",
                    "online": True,
                    "on": movement in ("cleaning",),
                    "cur_power": None,
                    "extra": ", ".join(extra_parts),
                    "kind": "vacuum",
                    "movement": movement,
                    "battery": battery,
                })
    except Exception:
        log.exception("tablet_vacuum_failed")

    # Инвертор + автономность
    try:
        from src.integrations.luxcloud import LuxCloudClient
        lux = _cached_client("luxcloud", lambda: LuxCloudClient.from_settings(settings))
        if lux:
            rt = await asyncio.wait_for(lux.runtime(), timeout=5.0)
            grid_import = rt.get("grid_import_w") or 0
            grid_export = rt.get("grid_export_w") or 0
            charge_w = rt.get("battery_charge_w") or 0
            discharge_w = rt.get("battery_discharge_w") or 0
            state["inverter"] = {
                "online": rt.get("online"),
                # SOC: LuxCloud возвращает battery_pct; старые названия
                # оставляем для обратной совместимости
                "soc": rt.get("battery_pct") if rt.get("battery_pct") is not None else (rt.get("soc") or rt.get("battery_soc")),
                "load_w": rt.get("home_consumption_w") or rt.get("load_w") or rt.get("home_w"),
                # Сеть считаем активной если через неё что-то течёт (import
                # либо export), либо status инвертора не «off-grid».
                "grid_active": (grid_import > 20 or grid_export > 20 or
                                str(rt.get("status") or "").lower() not in ("off-grid", "offgrid", "island")),
                "solar_w": rt.get("pv_total_w") or rt.get("solar_w") or rt.get("pv_w"),
                "grid_import_w": grid_import,
                "grid_export_w": grid_export,
                "battery_charge_w": charge_w,
                "battery_discharge_w": discharge_w,
                # производный статус для UI
                "battery_flow": (
                    "charging" if charge_w > discharge_w + 20
                    else "discharging" if discharge_w > charge_w + 20
                    else "idle"
                ),
            }
    except Exception:
        log.exception("tablet_lux_failed")

    # Виртуальные устройства для плана квартиры (инвертор, пылесос)
    # чтобы юзер мог их привязать к иконкам на плане.
    try:
        inv = state.get("inverter") or {}
        # setdefault, а не «devices уже не None» — иначе сбой Tuya (квота,
        # таймаут, сеть) выше по коду гасил и виртуальный инвертор/пылесос
        # тоже, хотя их данные (LuxCloud/SmartThings) от Tuya не зависят.
        state.setdefault("devices", [])
        # Инвертор в списке — если пришли ЛЮБЫЕ данные (soc, load, online)
        has_inv_data = (
            inv.get("soc") is not None or inv.get("load_w") is not None
            or inv.get("online") is not None
        )
        if has_inv_data:
            # Онлайн если явно True или есть soc (данные пришли)
            is_online = bool(inv.get("online")) or inv.get("soc") is not None
            state["devices"].append({
                "id": "virtual:inverter",
                "name": "Инвертор",
                "online": is_online,
                "category": "inverter",
                "on": inv.get("battery_flow") == "discharging",
                "cur_power": inv.get("load_w"),
                "battery": inv.get("soc"),
                "virtual": True,
                "read_only": True,
            })
        vac = state.get("vacuum") or {}
        if vac.get("id"):
            state["devices"].append({
                "id": "virtual:vacuum:" + str(vac.get("id")),
                "name": vac.get("name") or "Пылесос",
                "online": True,
                "category": "vacuum",
                "on": vac.get("state_key") == "cleaning",
                "battery": vac.get("battery"),
                "virtual": True,
                "read_only": True,
            })
    except Exception:
        log.exception("tablet_virtual_devices_failed")


    # Список покупок из Google Sheets (если Ежедневник настроен)
    try:
        cal = (agents or {}).get("calendar") if agents else None
        sheets = getattr(cal, "_sheets", None) if cal else None
        if sheets and hasattr(sheets, "get_shopping_list"):
            items = await asyncio.wait_for(sheets.get_shopping_list(), timeout=5.0)
            state["shopping"] = [
                {"name": it.get("name", ""), "done": bool(it.get("done", False))}
                for it in (items or [])[:10]
            ]
    except Exception:
        log.exception("tablet_shopping_failed")

    # Тревога — источник правды ActiveAlert.
    # news_ingest создаёт запись при alert_start, удаляет при alert_clear,
    # а sweeper авто-закрывает после 60 мин тишины. То есть если запись
    # ЕСТЬ — тревога активна прямо сейчас.
    try:
        from sqlalchemy import select
        from src.db.models import ActiveAlert
        async with memory._engine.connect() as conn:
            row = (await conn.execute(
                select(ActiveAlert).order_by(ActiveAlert.started_at.desc()).limit(1)
            )).first()
        if row:
            aa = row[0] if hasattr(row, "_mapping") else row
            digest = None
            raw = getattr(aa, "digest_json", None)
            if raw:
                try:
                    import json as _json
                    digest = _json.loads(raw)
                except Exception:
                    digest = None
            state["alert"] = {
                "active": True,
                "region": getattr(aa, "region", None),
                "started_at": getattr(aa, "started_at", None),
                "last_update_at": getattr(aa, "last_update_at", None),
                "digest": digest,
            }
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
            events = await asyncio.wait_for(cal.list_upcoming(days=7), timeout=5.0)
            today = []
            for e in events[:20]:
                today.append({
                    "id": getattr(e, "event_id", ""),
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

    # Посылки Новой Почты — только те, что ещё не доставлены (карточка
    # на планшете сама скрывается, когда список пуст).
    try:
        from sqlalchemy import select
        from src.db.models import Parcel
        async with memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(Parcel).where(Parcel.delivered_at.is_(None))
                .order_by(Parcel.created_at.desc()).limit(10)
            ))
        state["parcels"] = [
            {
                "ttn": r.ttn,
                "title": r.title or r.ttn,
                "status": r.status or "",
                "member": r.member or "",
                "city_from": r.city_from or "",
                "city_to": r.city_to or "",
                "warehouse": r.warehouse or "",
                "weight_kg": r.weight_kg,
                "cost_uah": r.cost_uah,
                "scheduled_at": r.scheduled_at or "",
            }
            for r in rows
        ]
    except Exception:
        log.exception("tablet_parcels_failed")
        state["parcels"] = []

    return state


def _load_template() -> str:
    if not _TEMPLATE_PATH.exists():
        return "<html><body><h1>Template missing</h1></body></html>"
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def register_tablet_routes(
    app: FastAPI,
    memory: Any,
    settings: Any,
    agents_ref: dict,
    dispatcher: Any = None,
    parser: Any = None,
    registry: Any = None,
    bot_manager: Any = None,
) -> None:
    """Регистрируем /tablet и /api/tablet/* в существующем FastAPI-приложении.

    agents_ref — ссылка на словарь agents из main.py (позволяет действиям
    вызывать реальные обработчики агентов и Tuya).
    """
    expected_token = getattr(settings, "dashboard_token", "")

    @app.get("/tablet", response_class=HTMLResponse)
    async def tablet_page(token: str = Query("")):
        _check_token(token, expected_token)
        html = _load_template()
        # PWA-теги — устанавливаемое приложение (иконка, отдельное окно без
        # адресной строки), а не просто закладка браузера. Манифест несёт
        # токен в start_url, чтобы значок на главном экране открывался сразу,
        # без повторного логина.
        manifest_href = f"/tablet/manifest.json?token={token}"
        head_tags = (
            '<!doctype html>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="theme-color" content="#b8862e">\n'
            f'<link rel="manifest" href="{manifest_href}">\n'
            '<link rel="apple-touch-icon" href="/tablet/static/icon-192.png">\n'
            '<meta name="apple-mobile-web-app-capable" content="yes">\n'
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n'
            '<meta name="apple-mobile-web-app-title" content="Family HQ">\n'
        )
        html = head_tags + html
        # Инжектим токен в HTML чтобы JS мог использовать его для API-запросов,
        # плюс регистрируем service worker (нужен для полноценной установки).
        html = html.replace(
            "<script>",
            f"<script>window.TABLET_TOKEN = {json.dumps(token)};"
            "if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/tablet/sw.js'); }",
            1,
        )
        return HTMLResponse(html)

    @app.get("/tablet/manifest.json")
    async def tablet_manifest(token: str = Query("")):
        _check_token(token, expected_token)
        return JSONResponse({
            "name": "Family HQ",
            "short_name": "Family HQ",
            "start_url": f"/tablet?token={token}",
            "display": "standalone",
            "orientation": "any",
            "background_color": "#f5ecd5",
            "theme_color": "#b8862e",
            "icons": [
                {"src": "/tablet/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/tablet/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
        })

    @app.get("/tablet/sw.js")
    async def tablet_sw():
        return FileResponse(_STATIC_DIR / "sw.js", media_type="application/javascript")

    @app.get("/tablet/static/{filename}")
    async def tablet_static(filename: str):
        # Только иконки — не отдаём произвольные файлы по имени.
        if filename not in ("icon-192.png", "icon-512.png"):
            raise HTTPException(status_code=404)
        return FileResponse(_STATIC_DIR / filename, media_type="image/png")

    # Кеш последнего успешного snapshot'а — если сборка залипла и словили
    # таймаут, отдадим предыдущий вместо 502.
    _state_cache: dict = {"last": None, "at": 0.0}

    @app.get("/api/tablet/state")
    async def tablet_state(token: str = Query("")):
        _check_token(token, expected_token)
        import asyncio, time
        try:
            state = await asyncio.wait_for(
                _build_tablet_state(memory, settings, agents_ref),
                timeout=20.0,
            )
            _state_cache["last"] = state
            _state_cache["at"] = time.time()
            return JSONResponse(state)
        except asyncio.TimeoutError:
            log.warning("tablet_state_timeout", cached_age=time.time() - _state_cache["at"])
            if _state_cache["last"]:
                cached = {**_state_cache["last"], "_stale": True}
                return JSONResponse(cached)
            return JSONResponse({"error": "timeout, no cache"}, status_code=503)
        except Exception as e:
            log.exception("tablet_state_failed")
            if _state_cache["last"]:
                cached = {**_state_cache["last"], "_stale": True, "_error": str(e)[:200]}
                return JSONResponse(cached)
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    # ─── Синхронизация настроек между устройствами (телефон/планшет) ──
    # Хранится единым JSON-блобом в agent_settings под key='tablet_prefs'.
    # Разделения между пользователями нет — токен один на семью, что и
    # даёт «одинаковая настройка на всех экранах».
    @app.get("/api/tablet/settings")
    async def tablet_settings_get(token: str = Query("")):
        _check_token(token, expected_token)
        try:
            raw = await memory.get_agent_setting("tablet", "prefs", "")
            import json as _json
            data = _json.loads(raw) if raw else {}
            return JSONResponse({"prefs": data})
        except Exception as e:
            log.exception("tablet_settings_get_failed")
            return JSONResponse({"prefs": {}, "error": str(e)[:200]})

    @app.post("/api/tablet/settings")
    async def tablet_settings_set(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        try:
            import json as _json
            prefs = payload.get("prefs")
            if not isinstance(prefs, dict):
                raise HTTPException(400, "prefs (object) required")
            # Ограничиваем размер, чтоб случайно не хранить в базе мегабайты
            body = _json.dumps(prefs, ensure_ascii=False)
            if len(body) > 200_000:
                raise HTTPException(413, "prefs too large")
            await memory.set_agent_setting("tablet", "prefs", body)
            return {"success": True, "bytes": len(body)}
        except HTTPException:
            raise
        except Exception as e:
            log.exception("tablet_settings_set_failed")
            return {"success": False, "error": str(e)[:200]}

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

    @app.post("/api/tablet/action/home-state")
    async def action_home_state(payload: dict = Body(...), token: str = Query("")):
        """Переключение «Уехали из дома» ↔ «Я дома». Персистится в
        agent_settings[tablet:home_state] и читается движком
        автоматизаций (family_away / family_home)."""
        _check_token(token, expected_token)
        state_val = (payload.get("state") or "").lower()
        if state_val not in ("home", "away"):
            raise HTTPException(400, "state must be home|away")
        try:
            await memory.set_agent_setting("tablet", "home_state", state_val)
            return {"success": True, "state": state_val}
        except Exception as e:
            log.exception("tablet_home_state_failed")
            return {"success": False, "error": str(e)[:200]}

    @app.post("/api/tablet/action/vacuum")
    async def action_vacuum(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        cmd = (payload.get("cmd") or "").lower()   # start / stop / pause / home
        if cmd not in ("start", "stop", "pause", "home"):
            raise HTTPException(400, "cmd must be one of start/stop/pause/home")
        try:
            from src.integrations.smartthings import SmartThingsClient
            st = SmartThingsClient.from_settings(settings, memory=memory)
            if not st:
                return {"success": False, "error": "smartthings not configured"}
            devices_st = await st.list_devices()
            vac = st.find_vacuum(devices_st, "гоша") or st.find_vacuum(devices_st)
            if not vac:
                return {"success": False, "error": "vacuum not found"}
            vid = vac["id"]
            if cmd == "start":
                await st.vacuum_start(vid, mode="auto")
            elif cmd == "pause":
                await st.vacuum_pause(vid)
            elif cmd in ("stop", "home"):
                await st.vacuum_stop(vid)
            return {"success": True}
        except Exception as e:
            log.exception("tablet_vacuum_action_failed")
            return {"success": False, "error": str(e)[:200]}

    # ─── События календаря семьи: добавить / удалить ─────────────────
    @app.post("/api/tablet/action/event")
    async def action_event(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        op = (payload.get("op") or "").lower()  # add | delete
        if op not in ("add", "delete"):
            raise HTTPException(400, "op must be add|delete")
        if not (settings.google_service_account_json and settings.calendar_id):
            return {"success": False, "error": "calendar not configured"}
        try:
            from src.integrations.gcalendar import CalendarClient
            from src.utils.time import now_kyiv
            from datetime import timedelta
            cal = CalendarClient(settings.google_service_account_json, settings.calendar_id)
            if op == "add":
                title = (payload.get("title") or "").strip()
                if not title:
                    raise HTTPException(400, "title required")
                time_str = (payload.get("time") or "").strip()  # 'HH:MM' or ''
                now = now_kyiv()
                if time_str and ":" in time_str:
                    try:
                        h, m = time_str.split(":")
                        start = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                        if start < now:                # если время в прошлом — на завтра
                            start = start + timedelta(days=1)
                    except ValueError:
                        start = now.replace(hour=12, minute=0, second=0, microsecond=0)
                else:
                    # весь день — 09:00 по умолчанию
                    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
                    if start < now:
                        start = start + timedelta(days=1)
                await cal.create_event(title=title, start=start)
                return {"success": True}
            else:  # delete
                event_id = (payload.get("id") or "").strip()
                if not event_id:
                    raise HTTPException(400, "id required")
                ok = await cal.delete_event(event_id)
                return {"success": bool(ok)}
        except HTTPException:
            raise
        except Exception as e:
            log.exception("tablet_event_action_failed")
            return {"success": False, "error": str(e)[:200]}

    # ─── Автоматизации: toggle / delete / add (через LLM Прораба) ─────
    @app.post("/api/tablet/action/automation")
    async def action_automation(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        op = (payload.get("op") or "").lower()
        if op not in ("toggle", "delete", "add", "enable", "disable"):
            raise HTTPException(400, "op must be toggle|delete|add")
        try:
            from sqlalchemy import select, update as sql_update, delete as sql_delete
            from src.db.models import AutomationRule
            if op in ("toggle", "enable", "disable"):
                rid = payload.get("id")
                if not rid:
                    raise HTTPException(400, "id required")
                async with memory._engine.begin() as conn:
                    # Читаем текущее enabled — простым скалярным запросом,
                    # без ORM-загрузки, чтобы избежать неоднозначности
                    # с обёртками Row в conn.execute (в SA2 select(Model)
                    # через conn возвращает Row[Row[Model]] и .first()
                    # даёт скалар — но в разных версиях по-разному).
                    cur = (await conn.execute(
                        select(AutomationRule.enabled).where(AutomationRule.id == int(rid))
                    )).scalar_one_or_none()
                    if cur is None:
                        return {"success": False, "error": "not found"}
                    new_enabled = 0 if op == "disable" else (1 if op == "enable" else (0 if cur else 1))
                    await conn.execute(sql_update(AutomationRule)
                        .where(AutomationRule.id == int(rid))
                        .values(enabled=new_enabled))
                return {"success": True, "enabled": bool(new_enabled)}
            if op == "delete":
                rid = payload.get("id")
                if not rid:
                    raise HTTPException(400, "id required")
                async with memory._engine.begin() as conn:
                    await conn.execute(sql_delete(AutomationRule).where(AutomationRule.id == int(rid)))
                return {"success": True}
            if op == "add":
                # Пересылаем текст Прорабу через диспетчер: он распарсит
                # и сам вызовет свой инструмент _automation_add с JSON.
                text = (payload.get("text") or "").strip()
                if not text:
                    raise HTTPException(400, "text required")
                devops = (agents_ref or {}).get("devops") if agents_ref else None
                if not devops:
                    return {"success": False, "error": "Прораб не подключён в этом деплое"}
                try:
                    from src.orchestrator.conversation import ConversationContext
                    from sqlalchemy import select as _sel, func as _func
                    ctx = ConversationContext(memory, settings.hq_chat_id)
                    # Считаем сколько правил было ДО
                    async with memory._engine.connect() as conn:
                        before = (await conn.execute(_sel(_func.count()).select_from(AutomationRule))).scalar_one()
                    resp = await devops.handle(
                        message_text=f"Создай автоматизацию: {text}",
                        sender_name="Консоль",
                        context=ctx,
                        parsed_actions=None,
                    )
                    # ...ПОСЛЕ
                    async with memory._engine.connect() as conn:
                        after = (await conn.execute(_sel(_func.count()).select_from(AutomationRule))).scalar_one()
                    reply_text = getattr(resp, "text", "") or ""
                    return {
                        "success": True,
                        "created": bool(after > before),
                        "reply": reply_text[:600],
                    }
                except Exception as e:
                    log.exception("tablet_automation_add_via_devops_failed")
                    return {"success": False, "error": str(e)[:200]}
        except HTTPException:
            raise
        except Exception as e:
            log.exception("tablet_automation_action_failed")
            return {"success": False, "error": str(e)[:200]}

    # ─── Список покупок: добавить / отметить купленным / удалить ─────
    @app.post("/api/tablet/action/shopping")
    async def action_shopping(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        op = (payload.get("op") or "").lower()  # add | done | delete
        item = (payload.get("item") or "").strip()
        if op not in ("add", "done", "delete"):
            raise HTTPException(400, "op must be add|done|delete")
        if not item:
            raise HTTPException(400, "item required")
        try:
            from sqlalchemy import insert, delete, update, select
            from src.db.models import ShoppingItem
            from src.utils.time import iso_now
            async with memory._engine.begin() as conn:
                if op == "add":
                    await conn.execute(insert(ShoppingItem).values(
                        item=item, added_at=iso_now(), added_by="Консоль",
                    ))
                elif op == "done":
                    await conn.execute(update(ShoppingItem)
                        .where(ShoppingItem.item == item, ShoppingItem.done_at.is_(None))
                        .values(done_at=iso_now()))
                elif op == "delete":
                    await conn.execute(delete(ShoppingItem)
                        .where(ShoppingItem.item == item))
            return {"success": True}
        except Exception as e:
            log.exception("tablet_shopping_action_failed")
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

    @app.get("/api/tablet/baby-day")
    async def baby_day(token: str = Query("")):
        """Реальная хронология дня Матвея из Дневника (Google Sheets).
        Возвращает {date, stats, timeline[]} для модалки «Матвей · день»."""
        _check_token(token, expected_token)
        try:
            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            if not sheets:
                return {"timeline": [], "stats": {}, "date": ""}
            from src.integrations.baby_state_compute import _entry_dt, _kind_clean, _match, _SLEEP_START, _SLEEP_END, _WALK_START, _WALK_END
            from src.utils.time import now_kyiv
            now = now_kyiv()
            today = now.date()
            rows = await sheets.get_baby_diary(days=2)

            KIND_TAG = {
                "сон": "sleep", "sleep": "sleep",
                "еда": "food", "food": "food", "прикорм": "food",
                "лекарство": "food", "medicine": "food",
                "подгузник": "diaper", "diaper": "diaper",
                "прогулка": "walk", "walk": "walk",
                "поездка": "walk", "trip": "walk",
                "симптом": "symptom", "веха": "note", "заметка": "note",
            }
            KIND_LABEL = {
                "sleep": "Сон", "food": "Еда", "diaper": "Подгузник",
                "walk": "Прогулка", "symptom": "Симптом", "note": "Заметка",
            }

            # Разбираем и сегодня и вчера — ночной сон часто начинается
            # 21-23 вчера, заканчивается в 6-8 сегодня. Без вчерашних
            # записей мы теряем целый большой сон.
            timeline = []
            today_entries = []
            all_entries = []  # для расчёта сна с учётом переходов через полночь
            for r in rows:
                d = r.data
                dt = _entry_dt(d)
                if dt is None:
                    continue
                kraw = _kind_clean(d.get("kind", ""))
                tag = KIND_TAG.get(kraw, "note")
                ev = (d.get("event") or "").strip()
                note = (d.get("note") or "").strip() if isinstance(d, dict) else ""
                item = {"dt": dt, "kind": kraw, "tag": tag, "event": ev, "note": note}
                all_entries.append(item)
                if dt.date() == today:
                    today_entries.append(item)

            all_entries.sort(key=lambda x: x["dt"])
            today_entries.sort(key=lambda x: x["dt"])
            for e in today_entries:
                timeline.append({
                    "time": e["dt"].strftime("%H:%M"),
                    "event": e["event"] or KIND_LABEL.get(e["tag"], "—"),
                    "sub": e["note"],
                    "tag": e["tag"],
                    "tag_label": KIND_LABEL.get(e["tag"], e["tag"]),
                })

            # ── Считаем сон по парам (start → end) на всём окне 2 дня,
            #    но учитываем только пересечение с сегодня (00:00 → сейчас).
            #    Это правильно ловит ночной сон 21:30→6:14 и промежуточные
            #    ночные пробуждения.
            from datetime import timedelta as _td
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            sleep_pairs = []           # список (start_dt, end_dt) — end может быть None если ещё спит
            in_sleep_start = None
            for e in all_entries:
                if e["tag"] != "sleep":
                    continue
                if _match(e["event"], _SLEEP_START):
                    in_sleep_start = e["dt"]
                elif _match(e["event"], _SLEEP_END):
                    if in_sleep_start:
                        sleep_pairs.append((in_sleep_start, e["dt"]))
                        in_sleep_start = None
            # если ещё спит — открытый интервал до «сейчас»
            if in_sleep_start:
                sleep_pairs.append((in_sleep_start, now))

            def _overlap_min(a, b, lo, hi):
                s = max(a, lo); e = min(b, hi)
                return max(0, int((e - s).total_seconds() / 60))

            sleep_min = sum(_overlap_min(s, e, day_start, now) for s, e in sleep_pairs)
            wake_windows = sum(1 for e in today_entries
                               if e["tag"] == "sleep" and _match(e["event"], _SLEEP_END))

            feeds = [e for e in today_entries if e["tag"] == "food"]
            diapers = [e for e in today_entries if e["tag"] == "diaper"]

            breast = sum(1 for f in feeds if "груд" in (f["event"].lower() + f["kind"]))
            prikorm = sum(1 for f in feeds if "прикорм" in (f["event"].lower() + f["kind"]))
            poo = sum(1 for d in diapers if any(w in d["event"].lower() for w in ("как", "стул", "poo")))

            # Всего бодрствовал сегодня (грубо: 24ч минус сон)
            awake_min = max(0, int((now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()/60) - sleep_min)

            def fmt(m):
                h, mm = divmod(int(m), 60)
                return f"{h}ч {mm:02d}м" if h else f"{mm}м"

            stats = {
                "sleep_total": fmt(sleep_min) if sleep_min else "—",
                "awake_total": fmt(awake_min) if awake_min else "—",
                "wake_windows": wake_windows,
                "feeds_total": len(feeds),
                "feeds_breast": breast,
                "feeds_prikorm": prikorm,
                "diapers_total": len(diapers),
                "diapers_poo": poo,
            }

            months_ru = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"]
            date_label = f"{today.day} {months_ru[today.month-1]}"
            return {"date": date_label, "stats": stats, "timeline": timeline}
        except Exception as e:
            log.exception("tablet_baby_day_failed")
            return {"timeline": [], "stats": {}, "date": "", "error": str(e)[:200]}

    @app.get("/api/tablet/matvey/milestones")
    async def matvey_milestones(token: str = Query("")):
        _check_token(token, expected_token)
        try:
            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            if not sheets:
                return {"milestones": []}
            return {"milestones": await sheets.list_milestones(limit=60)}
        except Exception as e:
            log.exception("tablet_milestones_failed")
            return {"milestones": [], "error": str(e)[:200]}

    @app.post("/api/tablet/matvey/milestone")
    async def matvey_milestone_add(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        title = (payload.get("title") or "").strip()
        note = (payload.get("note") or "").strip()
        if not title:
            raise HTTPException(400, "title required")
        try:
            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            if not sheets:
                return {"success": False, "error": "sheets not configured"}
            from src.utils.time import now_kyiv
            res = await sheets.append_milestone(
                milestone=title, time=now_kyiv(), details=note, author="Планшет",
            )
            return {"success": True, "row": res.get("row")}
        except Exception as e:
            log.exception("tablet_milestone_add_failed")
            return {"success": False, "error": str(e)[:200]}

    @app.get("/api/tablet/matvey/photos")
    async def matvey_photos(token: str = Query(""), limit: int = 24):
        _check_token(token, expected_token)
        try:
            from sqlalchemy import select
            from src.db.models import BabyPhoto
            async with memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(BabyPhoto).order_by(BabyPhoto.created_at.desc()).limit(limit)
                ))
            out = []
            total = len(rows)
            for r in rows:
                # Считаем «показывабельным» ТОЛЬКО фото с Drive-бэкапом или
                # реально живым локальным файлом. local_path у большинства
                # старых записей — это стёртый tempfile, поэтому Drive
                # обязателен как источник правды.
                drive_id = (r.drive_file_id or "").strip() if isinstance(r.drive_file_id, str) else r.drive_file_id
                local_ok = bool(r.local_path) and Path(r.local_path).exists()
                if not drive_id and not local_ok:
                    continue
                out.append({
                    "id": r.id,
                    "age": r.age_label or "",
                    "caption": r.caption or "",
                    "created_at": r.created_at,
                    "url": f"/api/tablet/matvey/photo/{r.id}?token={token}",
                })
            return {"photos": out, "total_in_db": total, "shown": len(out)}
        except Exception as e:
            log.exception("tablet_photos_failed")
            return {"photos": [], "error": str(e)[:200]}

    def _svg_placeholder(reason: str) -> "Response":
        """Возвращаем читаемый плейсхолдер вместо сломанной иконки."""
        from fastapi import Response
        safe = (reason or "?")[:40].replace("<", "").replace(">", "")
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 220">'
            f'<rect width="180" height="220" fill="#1c1a17"/>'
            f'<text x="90" y="105" font-family="Georgia,serif" font-size="34" '
            f'fill="rgba(255,200,90,0.75)" text-anchor="middle">📷</text>'
            f'<text x="90" y="135" font-family="ui-sans-serif" font-size="9" '
            f'fill="rgba(255,220,150,0.7)" text-anchor="middle" '
            f'letter-spacing="0.05em">Нет превью</text>'
            f'<text x="90" y="155" font-family="ui-sans-serif" font-size="7" '
            f'fill="rgba(255,220,150,0.45)" text-anchor="middle">{safe}</text>'
            f'</svg>'
        )
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/api/tablet/matvey/photo/{photo_id}")
    async def matvey_photo_stream(photo_id: int, token: str = Query("")):
        _check_token(token, expected_token)
        cache_dir = Path("/tmp/matvey-photo-cache")
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            log.exception("photo_cache_mkdir_failed")
        try:
            from sqlalchemy import select
            from src.db.models import BabyPhoto
            async with memory._engine.connect() as conn:
                row = (await conn.execute(
                    select(BabyPhoto).where(BabyPhoto.id == photo_id)
                )).first()
            if not row:
                return _svg_placeholder("not found")
            bp = row[0] if hasattr(row, "_mapping") else row
            local = getattr(bp, "local_path", "")
            if local and Path(local).exists():
                return FileResponse(local)
            cached = cache_dir / f"{photo_id}.jpg"
            if cached.exists() and cached.stat().st_size > 0:
                return FileResponse(str(cached), media_type="image/jpeg")
            drive_id = getattr(bp, "drive_file_id", None)
            if not drive_id:
                return _svg_placeholder("no drive backup")
            drive_client = _shared_clients.get("drive")
            if drive_client is None:
                try:
                    from src.integrations.drive import DriveClient
                    drive_client = DriveClient.from_settings(settings)
                    if drive_client is not None:
                        _shared_clients["drive"] = drive_client
                except Exception:
                    log.exception("tablet_photo_drive_init_failed")
            if drive_client is None:
                return _svg_placeholder("drive not configured")
            try:
                ok = await drive_client.download(drive_id, str(cached))
            except Exception as e:
                log.exception("tablet_photo_drive_download_raised")
                return _svg_placeholder(f"drive err: {str(e)[:24]}")
            if not ok or not cached.exists() or cached.stat().st_size == 0:
                return _svg_placeholder("drive dl failed")
            return FileResponse(str(cached), media_type="image/jpeg")
        except Exception as e:
            log.exception("tablet_photo_stream_failed")
            return _svg_placeholder(f"err: {str(e)[:24]}")

    @app.get("/api/tablet/matvey/photos-debug")
    async def matvey_photos_debug(token: str = Query("")):
        """Диагностика: показывает по каждому фото где что живо."""
        _check_token(token, expected_token)
        try:
            from sqlalchemy import select
            from src.db.models import BabyPhoto
            async with memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(BabyPhoto).order_by(BabyPhoto.created_at.desc()).limit(30)
                ))
            drive_available = False
            try:
                from src.integrations.drive import DriveClient
                drive_available = DriveClient.from_settings(settings) is not None
            except Exception:
                pass
            out = []
            cache_dir = Path("/tmp/matvey-photo-cache")
            for r in rows:
                out.append({
                    "id": r.id,
                    "age": r.age_label,
                    "local_path": r.local_path,
                    "local_exists": bool(r.local_path) and Path(r.local_path).exists(),
                    "drive_file_id": r.drive_file_id,
                    "cached": (cache_dir / f"{r.id}.jpg").exists(),
                })
            return {"drive_configured": drive_available, "photos": out}
        except Exception as e:
            return {"error": str(e)[:300]}

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
                author="Консоль", details=note,
            )
            return {"success": True}
        except Exception as e:
            log.exception("tablet_baby_event_failed")
            return {"success": False, "error": str(e)[:200]}

    @app.post("/api/tablet/chat")
    async def tablet_chat(payload: dict = Body(...), token: str = Query("")):
        """Отправить сообщение в общий семейный чат — тот же поток что
        и в Телеграме. Сообщение сохраняется в общей БД messages (и
        поэтому появится и на планшете, и в HQ-чате в Телеге), а затем
        через Dispatcher идёт ВСЕМ подходящим агентам, а не только
        Дворецкому. Их ответы тоже автосохранятся через
        context.save_message и пойдут в оба места сразу."""
        _check_token(token, expected_token)
        text = (payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "text required")
        try:
            from src.orchestrator.conversation import ConversationContext
            from src.utils.time import iso_now
            from sqlalchemy import insert
            from src.db.models import Message
            chat_id = settings.hq_chat_id
            context = ConversationContext(memory, chat_id)

            # 1) Сохраняем сообщение пользователя в общий журнал.
            #    tg_message_id=0 у tablet-сообщений, agent_id=null.
            #    Если тут же продублировать в Telegram HQ-чат — Дозорный
            #    ingestor подтянет реальный id; но мы не блокируемся.
            async with memory._engine.begin() as conn:
                await conn.execute(insert(Message).values(
                    tg_message_id=0, chat_id=chat_id, user_id=None,
                    agent_id=None, text=f"[Консоль] {text}",
                    has_media=0, date=iso_now(),
                ))

            # 2) Дублируем в Telegram (чтоб видели там же).
            if bot_manager is not None:
                try:
                    bot = bot_manager._bots.get("butler") or bot_manager._bots.get("devops") \
                          or next(iter(bot_manager._bots.values()), None)
                    if bot:
                        await bot.send_message(chat_id, f"👤 [Консоль]: {text}")
                except Exception:
                    log.exception("tablet_chat_tg_mirror_failed")

            # 3) Пропускаем через Dispatcher — как в Телеграме. Если
            #    инфраструктура не пробрасывалась — фолбэк на butler.
            responses = []
            if dispatcher is not None and parser is not None and registry is not None:
                try:
                    result = await dispatcher.dispatch(
                        message_text=text,
                        sender_name="Консоль",
                        active_agent_ids=registry.active_ids(),
                        recent_context=None,
                    )
                    parsed = await parser.parse(text)
                    priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
                    sorted_tasks = sorted(result.tasks, key=lambda t: priority_order.get(t.priority, 99))
                    for task in sorted_tasks:
                        agent = agents_ref.get(task.agent_id)
                        if not agent:
                            continue
                        try:
                            resp = await agent.handle(
                                message_text=text,
                                sender_name="Консоль",
                                context=context,
                                parsed_actions=[a.model_dump() for a in parsed.actions],
                            )
                            if resp and getattr(resp, "text", None):
                                responses.append({
                                    "agent_id": task.agent_id,
                                    "text": resp.text,
                                })
                        except Exception:
                            log.exception("tablet_chat_agent_failed", agent_id=task.agent_id)
                except Exception:
                    log.exception("tablet_chat_dispatch_failed")
            # Фолбэк — Butler
            if not responses:
                butler = agents_ref.get("butler") if agents_ref else None
                if butler:
                    resp = await butler.handle(
                        message_text=text, sender_name="Консоль", context=context,
                    )
                    if resp and getattr(resp, "text", None):
                        responses.append({"agent_id": "butler", "text": resp.text})
            return {"success": True, "responses": responses}
        except Exception as e:
            log.exception("tablet_chat_failed")
            return {"success": False, "error": str(e)[:200]}

    @app.get("/api/tablet/chat/history")
    async def tablet_chat_history(token: str = Query(""), limit: int = Query(80)):
        """Последние N сообщений HQ-чата — и от пользователя (Телега/Консоль),
        и от агентов. Позволяет планшету показывать те же реплики что и
        Телеграм-чат."""
        _check_token(token, expected_token)
        try:
            from sqlalchemy import select, desc
            from src.db.models import Message
            chat_id = settings.hq_chat_id
            limit = max(1, min(int(limit or 80), 300))
            async with memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(Message.id, Message.tg_message_id, Message.user_id,
                           Message.agent_id, Message.text, Message.date)
                    .where(Message.chat_id == chat_id)
                    .order_by(desc(Message.date)).limit(limit)
                ))
            # Возвращаем в хронологическом порядке (старые первыми)
            items = []
            for r in reversed(rows):
                items.append({
                    "id": r[0],
                    "tg_id": r[1],
                    "user_id": r[2],
                    "agent_id": r[3],
                    "text": r[4] or "",
                    "date": r[5],
                })
            return {"items": items}
        except Exception as e:
            log.exception("tablet_chat_history_failed")
            return {"items": [], "error": str(e)[:200]}

    # ─────────────────────────────────────────────────────────────────
    # Прикорм: список пробованного (по категориям) + «на очереди» по возрасту
    # ─────────────────────────────────────────────────────────────────
    @app.get("/api/tablet/feeding/products")
    async def tablet_feeding_products(token: str = Query("")):
        _check_token(token, expected_token)
        try:
            from src.utils.food_catalog import (
                CATEGORIES, guess_emoji, guess_category, to_try_now,
            )
            from src.utils.baby import MATVEY_BIRTH_DATE
            from datetime import date

            age_months = (date.today() - MATVEY_BIRTH_DATE).days / 30.4375

            # Читаем «Прикорм» из Sheets — уже введённые продукты
            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            rows = []
            if sheets:
                try:
                    rows = await sheets.get_feeding(limit=1000)
                except Exception as e:
                    log.warning("feeding_sheets_read_failed", err=str(e)[:200])

            # Агрегируем по (product_norm) — берём последнюю запись как «свежую реакцию»
            from src.utils.food_catalog import _normalize
            aggr: dict[str, dict] = {}
            for r in rows:
                p = (r.get("product") or "").strip()
                if not p:
                    continue
                # Только «Прикорм» тип (не «Грудь», не «Смесь»)
                type_ = (r.get("type") or "").lower()
                if "прикорм" not in type_ and "▪ прикорм" not in type_ and type_ != "":
                    if any(x in type_ for x in ("груд", "смес", "молок")):
                        continue
                key = _normalize(p)
                if not key:
                    continue
                cur = aggr.get(key)
                item = {
                    "name": p,
                    "norm": key,
                    "emoji": guess_emoji(p),
                    "category": guess_category(p),
                    "last_reaction": r.get("reaction", ""),
                    "last_date": r.get("date", ""),
                    "count": (cur["count"] + 1) if cur else 1,
                }
                if cur:
                    # Оставляем последнюю по номеру строки (Sheets append-only,
                    # позже = свежее). Атрибут count суммируем.
                    item["count"] = cur["count"] + 1
                aggr[key] = item

            # Раскладываем по категориям
            tried_by_cat: dict[str, dict] = {}
            for cat_slug, cat_em in CATEGORIES:
                tried_by_cat[cat_slug] = {"emoji": cat_em, "items": []}
            for item in aggr.values():
                cat = item["category"]
                if cat not in tried_by_cat:
                    tried_by_cat[cat] = {"emoji": "🥄", "items": []}
                tried_by_cat[cat]["items"].append(item)
            # Сортируем внутри каждой категории по имени
            for cat in tried_by_cat.values():
                cat["items"].sort(key=lambda x: x["name"].lower())

            # На очереди — рекомендованные по возрасту, чего ещё не ели
            to_try = to_try_now(age_months, set(aggr.keys()))

            return {
                "age_months": round(age_months, 1),
                "tried_by_category": tried_by_cat,
                "to_try": to_try,
            }
        except Exception as e:
            log.exception("tablet_feeding_products_failed")
            return {"error": str(e)[:200], "tried_by_category": {}, "to_try": [], "age_months": 0}

    @app.get("/api/tablet/feeding/emoji")
    async def tablet_feeding_emoji(token: str = Query(""), name: str = Query("")):
        _check_token(token, expected_token)
        from src.utils.food_catalog import guess_emoji, guess_category
        return {
            "emoji": guess_emoji(name),
            "category": guess_category(name),
        }

    @app.post("/api/tablet/feeding/log")
    async def tablet_feeding_log(token: str = Query(""), body: dict = Body(...)):
        _check_token(token, expected_token)
        try:
            product = (body.get("product") or "").strip()
            if not product:
                return {"success": False, "error": "empty product"}
            portion = (body.get("portion") or "").strip()
            reaction_phys = (body.get("reaction_physical") or "").strip()
            reaction_ment = (body.get("reaction_mental") or "").strip()
            notes = (body.get("notes") or "").strip()

            # Соединяем физ и ментальную реакции — маппим на существующие
            # префиксы Гурмана (✅/⚠/😐/🙅/…)
            reaction_label = ""
            phys_map = {
                "ok": "хорошая", "все ок": "хорошая",
                "sy": "плохая", "сыпь": "плохая",
                "stul": "нейтральная", "срыгнул": "нейтральная",
                "reddening": "плохая", "покраснения": "плохая",
            }
            ment_map = {
                "liked": "отличная", "понравилось": "отличная",
                "neutral": "нейтральная", "нейтрально": "нейтральная",
                "grimace": "нейтральная", "кривлялся": "нейтральная",
                "refused": "отказался", "отказался": "отказался",
            }
            # Приоритет: если есть плохая физ. реакция — она главнее
            if reaction_phys and reaction_phys.lower() not in ("ok", "все ок", ""):
                reaction_label = phys_map.get(reaction_phys.lower(), "нейтральная")
            elif reaction_ment:
                reaction_label = ment_map.get(reaction_ment.lower(), "нейтральная")
            else:
                reaction_label = "хорошая"

            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            if not sheets:
                return {"success": False, "error": "sheets not available"}
            from src.utils.time import now_kyiv
            details_parts = []
            if reaction_phys and reaction_phys.lower() not in ("ok", "все ок", ""):
                details_parts.append(f"физ: {reaction_phys}")
            if reaction_ment:
                details_parts.append(f"понр: {reaction_ment}")
            if notes:
                details_parts.append(notes)
            details = " · ".join(details_parts)

            result = await sheets.append_feeding(
                type_="прикорм",
                product=product,
                time=now_kyiv(),
                portion=portion,
                reaction=reaction_label,
                details=details,
                author="Планшет",
            )
            return {"success": True, **result}
        except Exception as e:
            log.exception("tablet_feeding_log_failed")
            return {"success": False, "error": str(e)[:200]}

    # ─────────────────────────────────────────────────────────────────
    # Рост и вес Матвея — из «Рост» Google Sheets + WHO перцентили
    # ─────────────────────────────────────────────────────────────────
    @app.get("/api/tablet/growth")
    async def tablet_growth(token: str = Query("")):
        _check_token(token, expected_token)
        try:
            from src.utils.baby import MATVEY_BIRTH_DATE
            from src.utils.who import (
                _BOY_WEIGHT, _BOY_HEIGHT, weight_percentile, height_percentile,
            )
            from datetime import date, datetime

            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            rows = []
            if sheets:
                try:
                    rows = await sheets.get_growth(limit=200)
                except Exception as e:
                    log.warning("growth_sheets_read_failed", err=str(e)[:200])

            def _parse_date(s: str):
                for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try: return datetime.strptime(s, fmt).date()
                    except ValueError: pass
                return None

            # Точки для графика — только те где дата парсится + вес/рост есть
            weight_pts = []   # {age_months, kg, date}
            height_pts = []   # {age_months, cm, date}
            for r in rows:
                d = _parse_date(r.get("date", ""))
                if not d: continue
                age_days = (d - MATVEY_BIRTH_DATE).days
                if age_days < 0: continue
                age_m = age_days / 30.4375
                w = r.get("weight_g")
                h = r.get("height_cm")
                if w and w > 0:
                    weight_pts.append({"age_months": round(age_m, 2), "kg": w/1000, "date": d.isoformat()})
                if h and h > 0:
                    height_pts.append({"age_months": round(age_m, 2), "cm": h, "date": d.isoformat()})

            weight_pts.sort(key=lambda p: p["age_months"])
            height_pts.sort(key=lambda p: p["age_months"])

            # Актуальные значения (последняя точка каждого ряда)
            last_w = weight_pts[-1] if weight_pts else None
            last_h = height_pts[-1] if height_pts else None
            age_days_now = (date.today() - MATVEY_BIRTH_DATE).days
            age_m_now = age_days_now / 30.4375

            # Дельта за месяц (сколько прибавил за последние ~30 дней)
            def _delta_per_month(pts, key):
                if len(pts) < 2: return None
                latest = pts[-1]
                target_age = latest["age_months"] - 1.0
                # ближайшая точка ~месяц назад
                prev = min(pts[:-1], key=lambda p: abs(p["age_months"] - target_age), default=None)
                if not prev: return None
                dm = latest["age_months"] - prev["age_months"]
                if dm <= 0: return None
                return round((latest[key] - prev[key]) / dm, 2)

            wt_percentile = None
            ht_percentile = None
            if last_w:
                p = weight_percentile(last_w["kg"], int(round(age_m_now)))
                wt_percentile = {"bucket": p["bucket"], "ref": p["reference_kg"]}
            if last_h:
                p = height_percentile(last_h["cm"], int(round(age_m_now)))
                ht_percentile = {"bucket": p["bucket"], "ref": p["reference_cm"]}

            # WHO reference band — точки для построения полосы 3-97% и медианы
            def _who_band(table):
                out = []
                for age_key in sorted(table.keys()):
                    p3,p15,p50,p85,p97 = table[age_key]
                    out.append({"age_months": age_key, "p3":p3, "p15":p15, "p50":p50, "p85":p85, "p97":p97})
                return out

            return {
                "age_months": round(age_m_now, 1),
                "weight": {
                    "latest_kg": last_w["kg"] if last_w else None,
                    "latest_date": last_w["date"] if last_w else None,
                    "delta_kg_per_month": _delta_per_month(weight_pts, "kg"),
                    "percentile": wt_percentile,
                    "history": weight_pts,
                    "who_band": _who_band(_BOY_WEIGHT),
                },
                "height": {
                    "latest_cm": last_h["cm"] if last_h else None,
                    "latest_date": last_h["date"] if last_h else None,
                    "delta_cm_per_month": _delta_per_month(height_pts, "cm"),
                    "percentile": ht_percentile,
                    "history": height_pts,
                    "who_band": _who_band(_BOY_HEIGHT),
                },
            }
        except Exception as e:
            log.exception("tablet_growth_failed")
            return {"error": str(e)[:200]}

    @app.post("/api/tablet/growth/log")
    async def tablet_growth_log(token: str = Query(""), body: dict = Body(...)):
        _check_token(token, expected_token)
        try:
            from src.utils.time import now_kyiv
            w = body.get("weight_g")
            h = body.get("height_cm")
            notes = (body.get("notes") or "").strip()
            if w is None and h is None:
                return {"success": False, "error": "need weight_g or height_cm"}
            try:
                w = int(w) if w is not None else None
                h = float(h) if h is not None else None
            except (TypeError, ValueError):
                return {"success": False, "error": "bad number"}
            nanny = agents_ref.get("nanny") if agents_ref else None
            sheets = getattr(nanny, "_sheets", None) if nanny else None
            if not sheets:
                return {"success": False, "error": "sheets not available"}
            res = await sheets.append_growth(
                weight_g=w, height_cm=h, time=now_kyiv(), details=notes,
            )
            return {"success": True, **res}
        except Exception as e:
            log.exception("tablet_growth_log_failed")
            return {"success": False, "error": str(e)[:200]}

    # ─────────────────────────────────────────────────────────────────
    # Apple Music — генерация developer token из .p8 ключа
    # ─────────────────────────────────────────────────────────────────
    _music_token_cache: dict = {"token": None, "exp": 0.0}

    @app.get("/api/tablet/music/token")
    async def tablet_music_token(token: str = Query("")):
        _check_token(token, expected_token)
        import time
        team_id = (getattr(settings, "apple_music_team_id", "") or "").strip()
        key_id  = (getattr(settings, "apple_music_key_id", "") or "").strip()
        p8_text = (getattr(settings, "apple_music_key_p8", "") or "").strip()
        p8_path = (getattr(settings, "apple_music_key_path", "") or "").strip()

        if not team_id or not key_id or (not p8_text and not p8_path):
            return {"configured": False, "reason": "Ключи Apple Music не настроены"}

        if not p8_text and p8_path:
            try:
                with open(p8_path) as f: p8_text = f.read()
            except Exception as e:
                return {"configured": False, "reason": f"не могу прочитать key_path: {e}"}

        # Нормализуем формат ключа (поддержка одной строки без переносов)
        if "-----BEGIN" not in p8_text:
            body = "".join(p8_text.split())
            p8_text = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(
                body[i:i+64] for i in range(0, len(body), 64)
            ) + "\n-----END PRIVATE KEY-----\n"

        now = int(time.time())
        # Токен валиден до 6 месяцев (максимум по Apple)
        exp = now + int(60 * 60 * 24 * 180 * 0.95)  # 95% от 6 мес — обновляем заранее

        cached = _music_token_cache
        if cached["token"] and cached["exp"] - now > 60 * 60 * 24:
            return {"configured": True, "token": cached["token"], "expires_at": cached["exp"]}

        try:
            import jwt as pyjwt
        except ImportError:
            return {"configured": False, "reason": "PyJWT не установлен на сервере"}

        try:
            token_str = pyjwt.encode(
                payload={"iss": team_id, "iat": now, "exp": exp},
                key=p8_text,
                algorithm="ES256",
                headers={"alg": "ES256", "kid": key_id},
            )
            _music_token_cache["token"] = token_str
            _music_token_cache["exp"] = exp
            return {"configured": True, "token": token_str, "expires_at": exp}
        except Exception as e:
            log.exception("apple_music_token_failed")
            return {"configured": False, "reason": f"Ошибка подписи JWT: {str(e)[:150]}"}

    # ─────────────────────────────────────────────────────────────────
    # Spotify OAuth + прокси к Web API
    # ─────────────────────────────────────────────────────────────────
    from fastapi.responses import RedirectResponse

    # Полный набор scope (у владельца приложения теперь Premium — все работают).
    # 'streaming' даст возможность в будущем управлять плеером через
    # Web Playback SDK (без iframe).
    _SPOTIFY_SCOPES = " ".join([
        "user-read-private", "user-read-email",
        "user-library-read", "user-library-modify",
        "playlist-read-private", "playlist-read-collaborative",
        "user-read-recently-played", "user-top-read",
        "streaming",
        # Управление сессией — prev/play/pause/next из нашего UI
        "user-read-playback-state", "user-modify-playback-state",
        "user-read-currently-playing",
    ])

    async def _get_spotify_token() -> dict | None:
        """Читает access_token из БД, обновляет через refresh_token если истёк."""
        import time, base64, httpx
        from sqlalchemy import select
        from src.db.models import OAuthToken
        async with memory._engine.connect() as conn:
            row = (await conn.execute(
                select(OAuthToken).where(OAuthToken.provider == "spotify")
            )).first()
        if not row:
            return None
        access = row.access_token
        refresh = row.refresh_token
        exp = int(row.expires_at or 0)
        now = int(time.time())
        if exp - now > 60:
            return {"access_token": access, "refresh_token": refresh, "expires_at": exp}
        # Обновляем
        cid = getattr(settings, "spotify_client_id", "")
        csec = getattr(settings, "spotify_client_secret", "")
        if not cid or not csec or not refresh:
            return None
        basic = base64.b64encode(f"{cid}:{csec}".encode()).decode()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "refresh_token", "refresh_token": refresh},
                headers={"Authorization": "Basic " + basic,
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            data = r.json()
        new_access = data["access_token"]
        new_refresh = data.get("refresh_token") or refresh
        new_exp = now + int(data.get("expires_in", 3600))
        await _save_spotify_token(new_access, new_refresh, new_exp, data.get("scope"))
        return {"access_token": new_access, "refresh_token": new_refresh, "expires_at": new_exp}

    async def _save_spotify_token(access: str, refresh: str | None, expires_at: int, scope: str | None):
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from src.db.models import OAuthToken
        from src.utils.time import now_kyiv
        async with memory._engine.begin() as conn:
            stmt = sqlite_insert(OAuthToken).values(
                provider="spotify",
                access_token=access,
                refresh_token=refresh,
                expires_at=expires_at,
                scope=scope,
                updated_at=now_kyiv().isoformat(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["provider"],
                set_={
                    "access_token": access,
                    "refresh_token": refresh,
                    "expires_at": expires_at,
                    "scope": scope,
                    "updated_at": now_kyiv().isoformat(),
                },
            )
            await conn.execute(stmt)

    def _spotify_redirect_uri() -> str:
        base = (getattr(settings, "spotify_redirect_base", "") or "").rstrip("/")
        return f"{base}/api/tablet/spotify/callback"

    @app.get("/api/tablet/spotify/status")
    async def spotify_status(token: str = Query("")):
        _check_token(token, expected_token)
        cid = getattr(settings, "spotify_client_id", "")
        base = getattr(settings, "spotify_redirect_base", "")
        if not cid or not base:
            return {"configured": False, "reason": "SPOTIFY_CLIENT_ID/SECRET/REDIRECT_BASE не заданы в Railway"}
        tok = await _get_spotify_token()
        return {"configured": True, "authorized": bool(tok)}

    @app.get("/api/tablet/spotify/login")
    async def spotify_login(token: str = Query("")):
        _check_token(token, expected_token)
        import urllib.parse, secrets
        cid = getattr(settings, "spotify_client_id", "")
        if not cid:
            raise HTTPException(400, "spotify not configured")
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": cid,
            "response_type": "code",
            "redirect_uri": _spotify_redirect_uri(),
            "scope": _SPOTIFY_SCOPES,
            "state": state,
        }
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
        return RedirectResponse(url)

    @app.get("/api/tablet/spotify/callback")
    async def spotify_callback(code: str = Query(""), state: str = Query(""), error: str = Query("")):
        import base64, httpx, time
        if error:
            return HTMLResponse(f"<h2>Ошибка Spotify: {error}</h2>", status_code=400)
        if not code:
            return HTMLResponse("<h2>Нет code от Spotify</h2>", status_code=400)
        cid = getattr(settings, "spotify_client_id", "")
        csec = getattr(settings, "spotify_client_secret", "")
        basic = base64.b64encode(f"{cid}:{csec}".encode()).decode()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _spotify_redirect_uri(),
                },
                headers={"Authorization": "Basic " + basic,
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            if r.status_code != 200:
                return HTMLResponse(f"<h2>Spotify отказал: {r.status_code}</h2><pre>{r.text}</pre>", status_code=400)
            data = r.json()
        exp = int(time.time()) + int(data.get("expires_in", 3600))
        await _save_spotify_token(
            data["access_token"], data.get("refresh_token"), exp, data.get("scope"),
        )
        return HTMLResponse("""
            <html><body style="font-family:sans-serif;background:#1a1614;color:#ede6dc;text-align:center;padding:60px">
            <h1>✅ Spotify подключён!</h1>
            <p>Можешь закрыть эту вкладку и вернуться на планшет.</p>
            <script>setTimeout(()=>window.close(), 2000);</script>
            </body></html>
        """)

    @app.get("/api/tablet/spotify/logout")
    async def spotify_logout(token: str = Query("")):
        _check_token(token, expected_token)
        from sqlalchemy import delete
        from src.db.models import OAuthToken
        async with memory._engine.begin() as conn:
            await conn.execute(delete(OAuthToken).where(OAuthToken.provider == "spotify"))
        return {"success": True}

    # ═══════════════════════════════════════════════════════════════
    #                    SmartThings OAuth2 flow
    # PAT живёт 24ч — недобно. OAuth даёт refresh_token на ~30 дней,
    # мы сами перевыпускаем access_token в фоне через SmartThingsClient.
    # ═══════════════════════════════════════════════════════════════

    _SMARTTHINGS_SCOPES = " ".join([
        "r:devices:*", "x:devices:*", "r:locations:*",
    ])

    def _smartthings_redirect_uri() -> str:
        base = (getattr(settings, "smartthings_redirect_base", "")
                or getattr(settings, "spotify_redirect_base", "") or "").rstrip("/")
        return f"{base}/api/tablet/smartthings/callback"

    @app.get("/api/tablet/smartthings/status")
    async def smartthings_status(token: str = Query("")):
        _check_token(token, expected_token)
        cid = getattr(settings, "smartthings_client_id", "")
        base = getattr(settings, "smartthings_redirect_base", "") or getattr(settings, "spotify_redirect_base", "")
        pat = getattr(settings, "smartthings_token", "")
        if not (cid and base):
            return {
                "configured": False, "mode": "pat" if pat else "none",
                "reason": "SMARTTHINGS_CLIENT_ID/SECRET/REDIRECT_BASE не заданы. "
                          "Работает PAT-режим (истекает 24ч)." if pat else
                          "SmartThings не настроен ни через OAuth ни через PAT.",
            }
        # Проверяем есть ли OAuth-токен в БД
        from sqlalchemy import select
        from src.db.models import OAuthToken
        async with memory._engine.connect() as conn:
            row = (await conn.execute(
                select(OAuthToken).where(OAuthToken.provider == "smartthings")
            )).first()
        return {"configured": True, "mode": "oauth", "authorized": bool(row)}

    @app.get("/api/tablet/smartthings/login")
    async def smartthings_login(token: str = Query("")):
        _check_token(token, expected_token)
        import urllib.parse, secrets as _secrets
        cid = getattr(settings, "smartthings_client_id", "")
        if not cid:
            raise HTTPException(400, "SmartThings OAuth не настроен: нет CLIENT_ID")
        params = {
            "client_id": cid,
            "response_type": "code",
            "redirect_uri": _smartthings_redirect_uri(),
            "scope": _SMARTTHINGS_SCOPES,
            "state": _secrets.token_urlsafe(16),
        }
        url = "https://api.smartthings.com/oauth/authorize?" + urllib.parse.urlencode(params)
        return RedirectResponse(url)

    @app.get("/api/tablet/smartthings/callback")
    async def smartthings_callback(code: str = Query(""), state: str = Query(""), error: str = Query("")):
        import base64, httpx, time as _time
        from src.utils.time import now_kyiv
        if error:
            return HTMLResponse(f"<h2>SmartThings ошибка: {error}</h2>", status_code=400)
        if not code:
            return HTMLResponse("<h2>Нет code от SmartThings</h2>", status_code=400)
        cid = getattr(settings, "smartthings_client_id", "")
        csec = getattr(settings, "smartthings_client_secret", "")
        basic = base64.b64encode(f"{cid}:{csec}".encode()).decode()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.smartthings.com/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _smartthings_redirect_uri(),
                },
                headers={
                    "Authorization": "Basic " + basic,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            if r.status_code != 200:
                return HTMLResponse(
                    f"<h2>SmartThings отказал: {r.status_code}</h2><pre>{r.text}</pre>",
                    status_code=400,
                )
            data = r.json()
        exp = int(_time.time()) + int(data.get("expires_in", 86400))
        from sqlalchemy import insert as _insert
        from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
        from src.db.models import OAuthToken
        async with memory._engine.begin() as conn:
            stmt = _sqlite_insert(OAuthToken).values(
                provider="smartthings",
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_at=exp,
                scope=data.get("scope"),
                updated_at=now_kyiv().isoformat(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["provider"],
                set_={
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token"),
                    "expires_at": exp,
                    "scope": data.get("scope"),
                    "updated_at": now_kyiv().isoformat(),
                },
            )
            await conn.execute(stmt)
        return HTMLResponse("""
            <html><body style="font-family:sans-serif;background:#1a1614;color:#ede6dc;text-align:center;padding:60px">
            <h1>✅ SmartThings подключён!</h1>
            <p>Гоша готов к работе. Токен сам обновится через ~30 дней.</p>
            <p>Можешь закрыть эту вкладку.</p>
            <script>setTimeout(()=>window.close(), 2000);</script>
            </body></html>
        """)

    @app.get("/api/tablet/smartthings/logout")
    async def smartthings_logout(token: str = Query("")):
        _check_token(token, expected_token)
        from sqlalchemy import delete
        from src.db.models import OAuthToken
        async with memory._engine.begin() as conn:
            await conn.execute(delete(OAuthToken).where(OAuthToken.provider == "smartthings"))
        return {"success": True}

    async def _spotify_get(path: str, params: dict | None = None):
        """Возвращает (data, error). data — dict если ок, error — dict {status, message} если нет.

        204 No Content от Spotify — это НЕ ошибка (например когда никто не слушает
        через Spotify Connect). Возвращаем (None, None) чтобы вызывающий сам
        решил как трактовать «пусто».
        """
        import httpx
        tok = await _get_spotify_token()
        if not tok:
            return None, {"status": 0, "message": "not authorized (нет access_token)"}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                "https://api.spotify.com/v1" + path,
                params=params or {},
                headers={"Authorization": "Bearer " + tok["access_token"]},
            )
            if r.status_code == 204:
                return None, None
            if r.status_code != 200:
                log.warning("spotify_api_failed", path=path, status=r.status_code, body=r.text[:200])
                # Пробуем распарсить Spotify-стандартный формат ошибок
                try:
                    j = r.json()
                    msg = (j.get("error", {}) or {}).get("message") or r.text[:200]
                except Exception:
                    msg = r.text[:200]
                # 401/403 обычно означают что пользователь дал OAuth ДО того как
                # мы добавили новые scopes (user-read-playback-state и т.п.).
                # Даём UI понятную подсказку.
                if r.status_code in (401, 403):
                    msg = f"{msg} · Возможно нужно перелогиниться в Spotify (новые права доступа)"
                return None, {"status": r.status_code, "message": msg}
            return r.json(), None

    async def _spotify_put(path: str, params: dict | None = None, json_body: Any = None):
        import httpx
        tok = await _get_spotify_token()
        if not tok:
            return None, {"status": 0, "message": "not authorized"}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.put(
                "https://api.spotify.com/v1" + path,
                params=params or {}, json=json_body,
                headers={"Authorization": "Bearer " + tok["access_token"],
                         "Content-Type": "application/json"},
            )
            if r.status_code in (200, 202, 204):
                return {}, None
            log.warning("spotify_put_failed", path=path, status=r.status_code, body=r.text[:200])
            try: msg = (r.json().get("error", {}) or {}).get("message") or r.text[:200]
            except Exception: msg = r.text[:200]
            return None, {"status": r.status_code, "message": msg}

    async def _spotify_post(path: str, params: dict | None = None):
        import httpx
        tok = await _get_spotify_token()
        if not tok:
            return None, {"status": 0, "message": "not authorized"}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.spotify.com/v1" + path, params=params or {},
                headers={"Authorization": "Bearer " + tok["access_token"]},
            )
            if r.status_code in (200, 202, 204):
                return {}, None
            log.warning("spotify_post_failed", path=path, status=r.status_code, body=r.text[:200])
            try: msg = (r.json().get("error", {}) or {}).get("message") or r.text[:200]
            except Exception: msg = r.text[:200]
            return None, {"status": r.status_code, "message": msg}

    @app.get("/api/tablet/spotify/devices")
    async def spotify_devices(token: str = Query("")):
        _check_token(token, expected_token)
        data, err = await _spotify_get("/me/player/devices")
        if err: return {"devices": [], "error": err}
        return {"devices": (data or {}).get("devices", [])}

    @app.get("/api/tablet/spotify/now-playing")
    async def spotify_now_playing(token: str = Query("")):
        _check_token(token, expected_token)
        data, err = await _spotify_get("/me/player")
        if err:
            return {"playing": False, "error": err}
        if not data:
            return {"playing": False}
        item = data.get("item") or {}
        album = item.get("album") or {}
        images = album.get("images") or []
        artists = [a.get("name", "") for a in (item.get("artists") or [])]
        return {
            "playing": bool(data.get("is_playing")),
            "progress_ms": data.get("progress_ms") or 0,
            "duration_ms": item.get("duration_ms") or 0,
            "track": item.get("name") or "",
            "artists": artists,
            "album": album.get("name") or "",
            "cover_url": (images[0].get("url") if images else "") or "",
            "device": (data.get("device") or {}).get("name") or "",
            "device_id": (data.get("device") or {}).get("id") or "",
            "device_volume": (data.get("device") or {}).get("volume_percent"),
            "shuffle": bool(data.get("shuffle_state")),
            "repeat": data.get("repeat_state") or "off",
        }

    @app.post("/api/tablet/spotify/play")
    async def spotify_play(payload: dict = Body(default_factory=dict), token: str = Query("")):
        _check_token(token, expected_token)
        params = {}
        dev = payload.get("device_id")
        if dev: params["device_id"] = dev
        body: dict = {}
        if payload.get("context_uri"): body["context_uri"] = payload["context_uri"]
        if payload.get("uris"): body["uris"] = payload["uris"]
        if "position_ms" in payload: body["position_ms"] = int(payload["position_ms"])
        _, err = await _spotify_put("/me/player/play", params=params, json_body=body or None)
        return {"success": err is None, "error": err}

    @app.post("/api/tablet/spotify/pause")
    async def spotify_pause(token: str = Query("")):
        _check_token(token, expected_token)
        _, err = await _spotify_put("/me/player/pause")
        return {"success": err is None, "error": err}

    @app.post("/api/tablet/spotify/next")
    async def spotify_next(token: str = Query("")):
        _check_token(token, expected_token)
        _, err = await _spotify_post("/me/player/next")
        return {"success": err is None, "error": err}

    @app.post("/api/tablet/spotify/previous")
    async def spotify_previous(token: str = Query("")):
        _check_token(token, expected_token)
        _, err = await _spotify_post("/me/player/previous")
        return {"success": err is None, "error": err}

    @app.post("/api/tablet/spotify/seek")
    async def spotify_seek(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        pos = int(payload.get("position_ms") or 0)
        _, err = await _spotify_put("/me/player/seek", params={"position_ms": pos})
        return {"success": err is None, "error": err}

    @app.post("/api/tablet/spotify/volume")
    async def spotify_volume(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        vol = max(0, min(100, int(payload.get("volume_percent") or 0)))
        _, err = await _spotify_put("/me/player/volume", params={"volume_percent": vol})
        return {"success": err is None, "error": err}

    @app.post("/api/tablet/spotify/transfer")
    async def spotify_transfer(payload: dict = Body(...), token: str = Query("")):
        _check_token(token, expected_token)
        dev = payload.get("device_id")
        if not dev:
            raise HTTPException(400, "device_id required")
        play = bool(payload.get("play", True))
        _, err = await _spotify_put("/me/player", json_body={"device_ids": [dev], "play": play})
        return {"success": err is None, "error": err}

    @app.get("/api/tablet/spotify/me")
    async def spotify_me(token: str = Query("")):
        _check_token(token, expected_token)
        data, err = await _spotify_get("/me")
        if err: return {"error": err}
        return data or {}

    @app.get("/api/tablet/spotify/playlists")
    async def spotify_playlists(token: str = Query("")):
        """Все плейлисты пользователя — с пагинацией (Spotify отдаёт по 50)."""
        _check_token(token, expected_token)
        items = []
        offset = 0
        last_err = None
        while len(items) < 500:
            data, err = await _spotify_get("/me/playlists", {"limit": 50, "offset": offset})
            if err:
                last_err = err
                break
            if not data or not data.get("items"):
                break
            items.extend(data["items"])
            if not data.get("next"):
                break
            offset += 50
        out = {"items": items, "total": len(items)}
        if last_err and not items:
            out["error"] = last_err
        return out

    @app.get("/api/tablet/spotify/liked")
    async def spotify_liked(token: str = Query(""), limit: int = Query(50)):
        _check_token(token, expected_token)
        data, err = await _spotify_get("/me/tracks", {"limit": min(limit, 50)})
        if err: return {"items": [], "error": err}
        return data or {"items": []}

    @app.get("/api/tablet/spotify/playlist_tracks")
    async def spotify_playlist_tracks(id: str = Query(...), token: str = Query(""), limit: int = Query(100)):
        _check_token(token, expected_token)
        data, err = await _spotify_get(f"/playlists/{id}/tracks", {"limit": min(limit, 100)})
        if err: return {"items": [], "error": err}
        return data or {"items": []}

    @app.get("/api/tablet/spotify/search")
    async def spotify_search(q: str = Query(...), token: str = Query(""), types: str = Query("track,artist,album,playlist")):
        _check_token(token, expected_token)
        data, err = await _spotify_get("/search", {"q": q, "type": types, "limit": 10})
        if err: return {"error": err}
        return data or {}

    # ─────────────────────────────────────────────────────────────────
    # Голосовая транскрипция через Whisper (fallback для iOS Safari
    # где Web Speech API работает плохо).
    # ─────────────────────────────────────────────────────────────────
    from fastapi import UploadFile, File

    @app.post("/api/tablet/voice/transcribe")
    async def tablet_voice_transcribe(
        token: str = Query(""),
        file: UploadFile = File(...),
    ):
        _check_token(token, expected_token)
        try:
            from src.integrations.transcribe import TranscribeClient
            client = TranscribeClient.from_settings(settings)
            if not client:
                return {"success": False, "error": "OPENAI_API_KEY не настроен"}
            # Сохраняем во временный файл — TranscribeClient принимает path
            import tempfile, os
            ext = ".webm"
            if file.filename and "." in file.filename:
                ext = "." + file.filename.rsplit(".", 1)[-1]
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name
            try:
                text = await client.transcribe(tmp_path, language="ru")
                return {"success": True, "text": text}
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass
        except Exception as e:
            log.exception("voice_transcribe_failed")
            return {"success": False, "error": str(e)[:200]}

    log.info("tablet_routes_registered")
