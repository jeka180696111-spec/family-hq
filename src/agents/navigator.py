"""Штурман — trip planning, route, fuel, gas stations."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import insert, select, update as sql_update

from src.agents.base import BaseAgent
from src.db.models import FuelLog, Trip, Vehicle
from src.utils.time import iso_now, now_kyiv

log = structlog.get_logger()


class NavigatorAgent(BaseAgent):
    """Штурман: маршрут, расход, заправки, чек-лист."""

    agent_id = "navigator"
    emoji = "🧭"
    name = "Штурман"

    def get_system_prompt(self) -> str:
        from src.prompts.navigator import get_navigator_prompt
        return get_navigator_prompt(active_agents=[])

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "plan_trip",
                "description": (
                    "Запланировать поездку: расчёт маршрута через Google Maps, "
                    "оценка расхода топлива по машине, подбор заправок по маршруту "
                    "с приоритетом Укрнафта→WOG→OKKO. Сохраняет trip в БД."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "string", "description": "Откуда (город или адрес)"},
                        "destination": {"type": "string", "description": "Куда"},
                        "depart_at": {"type": "string", "description": "ISO datetime выезда (Kyiv TZ)"},
                        "return_at": {"type": "string", "description": "ISO datetime возврата (опц)"},
                        "notes": {"type": "string"},
                    },
                    "required": ["origin", "destination", "depart_at"],
                },
            },
            {
                "name": "log_fuel_from_receipt",
                "description": (
                    "Распознать чек АЗС с фото и записать заправку. "
                    "Если расход уточнить — обновит factual_l_100 для машины."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "image_path": {"type": "string", "description": "Локальный путь к фото чека"},
                        "odometer_km": {"type": "number", "description": "Текущий пробег (опц — если знаешь)"},
                    },
                    "required": ["image_path"],
                },
            },
            {
                "name": "log_fuel_manual",
                "description": "Записать заправку вручную без чека.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "station": {"type": "string"},
                        "liters": {"type": "number"},
                        "total_uah": {"type": "number"},
                        "odometer_km": {"type": "number"},
                        "fuel_kind": {"type": "string", "description": "A95/A92/дизель"},
                    },
                    "required": ["liters"],
                },
            },
            {
                "name": "vehicle_status",
                "description": "Текущее состояние машины: одометр, остаток в баке, средний расход.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "set_vehicle",
                "description": "Обновить параметры машины (одометр, бак, расходы).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "odometer_km": {"type": "number"},
                        "tank_remaining_l": {"type": "number"},
                        "avg_city_l_100": {"type": "number"},
                        "avg_highway_l_100": {"type": "number"},
                    },
                },
            },
            {
                "name": "list_trips",
                "description": "Показать предстоящие и активные поездки.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "cancel_trip",
                "description": "Отменить запланированную поездку и снять trip-mode jobs.",
                "input_schema": {
                    "type": "object",
                    "properties": {"trip_id": {"type": "integer"}},
                    "required": ["trip_id"],
                },
            },
            {
                "name": "save_route",
                "description": (
                    "Запомнить маршрут под именем для быстрого вызова: "
                    "«дача», «бабушка», «работа». Потом «поездка к бабушке» — "
                    "автоматически подставит origin/destination."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "origin": {"type": "string"},
                        "destination": {"type": "string"},
                    },
                    "required": ["name", "origin", "destination"],
                },
            },
            {
                "name": "list_saved_routes",
                "description": "Показать сохранённые маршруты.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "plan_saved_route",
                "description": "Запланировать поездку по сохранённому маршруту.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "depart_at": {"type": "string"},
                        "return_at": {"type": "string"},
                    },
                    "required": ["name", "depart_at"],
                },
            },
            {
                "name": "trip_check_now",
                "description": (
                    "Прислать обновлённую сводку по конкретной поездке сейчас: "
                    "свежий ETA с пробками, тревоги на маршруте, чек-лист."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"trip_id": {"type": "integer"}},
                    "required": ["trip_id"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "plan_trip":
            return await self._plan_trip(tool_input)
        if tool_name == "log_fuel_from_receipt":
            return await self._log_fuel_from_receipt(
                tool_input.get("image_path", ""),
                tool_input.get("odometer_km"),
            )
        if tool_name == "log_fuel_manual":
            return await self._log_fuel_manual(tool_input)
        if tool_name == "vehicle_status":
            return await self._vehicle_status()
        if tool_name == "set_vehicle":
            return await self._set_vehicle(tool_input)
        if tool_name == "list_trips":
            return await self._list_trips()
        if tool_name == "save_route":
            return await self._save_route(tool_input)
        if tool_name == "list_saved_routes":
            return await self._list_saved_routes()
        if tool_name == "plan_saved_route":
            return await self._plan_saved_route(tool_input)
        if tool_name == "cancel_trip":
            return await self._cancel_trip(int(tool_input.get("trip_id", 0)))
        if tool_name == "trip_check_now":
            await self._pre_trip_push(int(tool_input.get("trip_id", 0)))
            return {"status": "sent"}
        return await super()._call_tool(tool_name, tool_input)

    async def _save_route(self, p: dict) -> dict:
        from src.db.models import SavedRoute
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(SavedRoute).prefix_with("OR REPLACE").values(
                name=p["name"], origin=p["origin"], destination=p["destination"],
                times_used=0, created_at=iso_now(),
            ))
        return {"saved": p["name"]}

    async def _list_saved_routes(self) -> dict:
        from src.db.models import SavedRoute
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(SavedRoute).order_by(SavedRoute.times_used.desc())
            ))
        return {"routes": [
            {"name": r.name, "origin": r.origin, "destination": r.destination,
             "times_used": r.times_used, "last_used_at": r.last_used_at}
            for r in rows
        ]}

    async def _plan_saved_route(self, p: dict) -> dict:
        from src.db.models import SavedRoute
        name = p.get("name", "").strip().lower()
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(select(SavedRoute)))
        match = next((r for r in rows if name in r.name.lower()), None)
        if not match:
            return {"error": f"Маршрут '{name}' не найден. Список: {[r.name for r in rows]}"}
        async with self._memory._engine.begin() as conn:
            await conn.execute(sql_update(SavedRoute).where(SavedRoute.id == match.id).values(
                times_used=(match.times_used or 0) + 1,
                last_used_at=iso_now(),
            ))
        return await self._plan_trip({
            "origin": match.origin, "destination": match.destination,
            "depart_at": p["depart_at"], "return_at": p.get("return_at"),
            "notes": f"saved-route:{match.name}",
        })

    async def _cancel_trip(self, trip_id: int) -> dict:
        async with self._memory._engine.begin() as conn:
            await conn.execute(sql_update(Trip).where(Trip.id == trip_id).values(status="cancelled"))
        scheduler = getattr(self, "_scheduler", None)
        if scheduler:
            for jid in (f"trip_{trip_id}_pre", f"trip_{trip_id}_arm", f"trip_{trip_id}_disarm"):
                try:
                    scheduler.remove_job(jid)
                except Exception:
                    pass
        return {"cancelled": trip_id}

    # ─── plan_trip ────────────────────────────────────────────────────

    async def _plan_trip(self, p: dict) -> dict:
        from src.config import get_settings
        from src.integrations.gmaps import GMapsClient
        from src.utils.time import KYIV_TZ
        settings = get_settings()
        gmaps = GMapsClient.from_settings(settings)
        if not gmaps:
            return {"error": "Не настроен GMAPS_API_KEY"}

        try:
            depart_dt = datetime.fromisoformat(p["depart_at"])
            if depart_dt.tzinfo is None:
                depart_dt = depart_dt.replace(tzinfo=KYIV_TZ)
        except Exception:
            return {"error": "depart_at не парсится. Пиши '2026-06-10 09:00'"}

        try:
            route = await gmaps.directions(p["origin"], p["destination"], depart_dt)
        except Exception as e:
            return {"error": f"Маршрут не получен: {e}"}

        vehicle = await self._get_or_create_default_vehicle()
        # Highway-dominant assumption for inter-city trips: highway rate
        l_per_100 = vehicle.factual_l_100 or vehicle.avg_highway_l_100
        fuel_l = round(route["distance_km"] / 100 * l_per_100, 1)
        avg_price_uah = 56.0  # rough A95 average — учится позже из FuelLog
        try:
            last = await self._last_fuel_price(vehicle.id)
            if last:
                avg_price_uah = last
        except Exception:
            pass
        fuel_uah = round(fuel_l * avg_price_uah)

        # Gas stations along route
        stations: list[dict] = []
        try:
            stations = await gmaps.gas_stations_along_route(
                route["waypoints_latlng"], radius_m=3000, max_per_point=4,
            )
        except Exception:
            log.exception("gas_lookup_failed")

        top_stations = stations[:8]

        # Regions on the route → cross-check active alerts and recent strikes
        regions: list[str] = []
        try:
            regions = await gmaps.reverse_geocode_regions(route["waypoints_latlng"])
        except Exception:
            log.exception("reverse_geocode_failed")
        alert_warnings = await self._check_alerts_for_regions(regions)

        # Weather at destination in arrival window
        arrival_weather = await self._weather_at_arrival(
            p["destination"],
            depart_dt,
            route["duration_traffic_min"] or route["duration_min"],
        )

        # Pre-trip checklist
        checklist = self._build_checklist(
            distance_km=route["distance_km"],
            duration_min=route["duration_traffic_min"] or route["duration_min"],
            arrival_weather=arrival_weather,
            notes=(p.get("notes") or ""),
        )

        # Persist trip
        async with self._memory._engine.begin() as conn:
            result = await conn.execute(insert(Trip).values(
                vehicle_id=vehicle.id,
                origin=p["origin"], destination=p["destination"],
                depart_at=depart_dt.isoformat(),
                return_at=p.get("return_at"),
                distance_km=route["distance_km"],
                duration_min=route["duration_traffic_min"] or route["duration_min"],
                fuel_estimate_l=fuel_l,
                fuel_estimate_uah=fuel_uah,
                route_summary=json.dumps({
                    "summary": route["summary"],
                    "start": route["start_address"],
                    "end": route["end_address"],
                    "warnings": route["warnings"],
                    "stations": top_stations,
                    "regions": regions,
                    "alert_warnings": alert_warnings,
                    "arrival_weather": arrival_weather,
                    "checklist": checklist,
                }, ensure_ascii=False),
                status="planned",
                notes=p.get("notes"),
                created_at=iso_now(),
            ))
            trip_id = result.inserted_primary_key[0] if result.inserted_primary_key else None

        eta_min = route["duration_traffic_min"] or route["duration_min"]
        eta_h, eta_m = divmod(eta_min, 60)

        # Auto-arm trip: schedule one-shot jobs for trip-mode + pre-trip push
        arm_status = None
        if trip_id and depart_dt > now_kyiv():
            try:
                arm_status = self._arm_trip_jobs(
                    trip_id, depart_dt,
                    return_at=p.get("return_at"),
                )
            except Exception:
                log.exception("trip_arm_failed")

        # Google Maps ссылки: основной маршрут + кнопки на АЗС
        from urllib.parse import quote_plus as _qp
        origin_q = _qp(p["origin"])
        dest_q = _qp(p["destination"])
        # Топ-3 АЗС встраиваем как waypoints (Google Maps ограничивает 9),
        # чтобы юзер сразу видел их на карте как остановки.
        waypoints_urlpart = ""
        if top_stations:
            wp_encoded = "|".join(_qp(s["address"] or s["name"]) for s in top_stations[:3])
            waypoints_urlpart = f"&waypoints={wp_encoded}"
        route_url = (
            f"https://www.google.com/maps/dir/?api=1"
            f"&origin={origin_q}&destination={dest_q}"
            f"&travelmode=driving{waypoints_urlpart}"
        )
        waze_url = (
            f"https://www.waze.com/ul?ll={p['destination']}&navigate=yes&zoom=17"
        )

        # Ссылки на каждую АЗС на карте (юзер может кликнуть и увидеть
        # магазин рядом, туалет, кофейню — Google Maps покажет POI вокруг)
        stations_out: list[dict] = []
        for s in top_stations:
            addr = s.get("address") or s.get("name") or ""
            s_url = f"https://www.google.com/maps/search/?api=1&query={_qp(addr)}"
            stations_out.append({
                "name": s["name"],
                "address": s["address"],
                "map_url": s_url,
            })

        return {
            "trip_id": trip_id,
            "vehicle": vehicle.name,
            "route": route["summary"] or f"{route['start_address']} → {route['end_address']}",
            "distance_km": route["distance_km"],
            "eta_min": eta_min,
            "eta_pretty": f"{eta_h}ч {eta_m}мин",
            "fuel_l": fuel_l,
            "fuel_uah_estimate": fuel_uah,
            "l_per_100_used": l_per_100,
            "warnings": route["warnings"],
            "regions": regions,
            "alert_warnings": alert_warnings,
            "arrival_weather": arrival_weather,
            "checklist": checklist,
            "stations_top": stations_out,
            "route_url": route_url,
            "waze_url": waze_url,
            "arm_status": arm_status,
            "display_instruction": (
                "СТРОГИЙ ШАБЛОН ответа юзеру (все строки обязательны, "
                "порядок — как здесь):\n\n"
                "🧭 <origin> → <destination>\n"
                "📏 <distance_km> км, ⏱ <eta_pretty> (с пробками)\n"
                "⛽ Расход: ~<fuel_l>л, ~<fuel_uah_estimate> грн\n"
                "🛣 Через <regions через запятую>\n"
                "⚠️ <alert_warnings — если есть, иначе строку пропусти>\n"
                "🌤 В <destination> при прибытии: <arrival_weather коротко>\n"
                "⛽ АЗС по пути: <первые 3-5 из stations_top, каждая как "
                "<a href=\"map_url\">имя (адрес)</a>>\n"
                "✅ Чек-лист: <checklist через запятую>\n\n"
                "🗺 <a href=\"<route_url>\">Открыть маршрут в Google Maps</a>\n"
                "🚦 <a href=\"<waze_url>\">Открыть в Waze</a>\n\n"
                "В самом конце — короткая строка про arm_status (что trip-mode "
                "и напоминание за 30 мин взведены).\n"
                "Никаких вступлений, никакого «Женя, вот твой маршрут» — "
                "СРАЗУ с 🧭. Ссылки обязательно как HTML <a href>, не голым URL."
            ),
        }

    # ─── fuel logging ─────────────────────────────────────────────────

    async def _log_fuel_from_receipt(self, image_path: str, odometer_km: float | None) -> dict:
        try:
            import base64
            with open(image_path, "rb") as f:
                b64 = base64.standard_b64encode(f.read()).decode()
        except Exception as e:
            return {"error": f"Не могу прочитать фото: {e}"}

        # Ask Claude vision to extract
        try:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": b64,
                    }},
                    {"type": "text", "text": (
                        "Это чек украинской АЗС. Извлеки JSON: "
                        "{station: 'WOG|OKKO|Укрнафта|...', liters: число, "
                        "price_per_l: число грн, total_uah: число грн, "
                        "fuel_kind: 'A95|A92|A98|дизель|газ'}. "
                        "Только JSON, без пояснений. Если поле не видно — null."
                    )},
                ],
            }]
            raw = await self._claude.complete(
                model=self._get_model(), system="Ты — OCR чеков АЗС. Отдаёшь только JSON.",
                messages=messages, max_tokens=300,
            )
            parsed = _extract_json(raw)
        except Exception as e:
            return {"error": f"OCR не сработал: {e}"}

        vehicle = await self._get_or_create_default_vehicle()
        liters = parsed.get("liters")
        if not liters:
            return {"error": "Не удалось распознать литры. Кинь ещё раз или скажи вручную."}

        # Archive the receipt to Drive: ⛽ Чеки · АЗС / YYYY-MM /
        drive_url = None
        try:
            from src.config import get_settings
            from src.integrations.drive import DriveClient
            drive = DriveClient.from_settings(get_settings())
            if drive:
                folder_id = await drive.ensure_path([
                    "⛽ Чеки · АЗС", now_kyiv().strftime("%Y-%m"),
                ])
                station = (parsed.get("station") or "АЗС").replace("/", "-")
                fname = (
                    f"{now_kyiv().strftime('%Y-%m-%d_%H%M')}_{station}_"
                    f"{int(float(liters))}л.jpg"
                )
                result = await drive.upload(
                    image_path, fname, folder_id,
                    description=f"{station} · {liters}л · {parsed.get('total_uah') or '?'}₴",
                )
                drive_url = result.get("url")
        except Exception:
            log.exception("fuel_receipt_drive_upload_failed")

        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(FuelLog).values(
                vehicle_id=vehicle.id,
                station=parsed.get("station"),
                liters=float(liters),
                price_per_l=parsed.get("price_per_l"),
                total_uah=parsed.get("total_uah"),
                odometer_km=odometer_km,
                fuel_kind=parsed.get("fuel_kind"),
                receipt_path=drive_url or image_path,
                created_at=iso_now(),
            ))
        await self._maybe_update_factual_consumption(vehicle.id)
        return {"saved": True, "parsed": parsed, "drive_url": drive_url}

    async def _log_fuel_manual(self, p: dict) -> dict:
        vehicle = await self._get_or_create_default_vehicle()
        liters = float(p.get("liters", 0))
        if not liters:
            return {"error": "liters обязательно"}
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(FuelLog).values(
                vehicle_id=vehicle.id,
                station=p.get("station"),
                liters=liters,
                total_uah=p.get("total_uah"),
                price_per_l=(float(p["total_uah"]) / liters) if p.get("total_uah") else None,
                odometer_km=p.get("odometer_km"),
                fuel_kind=p.get("fuel_kind"),
                created_at=iso_now(),
            ))
        await self._maybe_update_factual_consumption(vehicle.id)
        return {"saved": True}

    async def _maybe_update_factual_consumption(self, vehicle_id: int) -> None:
        """If two consecutive fills have odometer — compute real L/100km."""
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(FuelLog).where(FuelLog.vehicle_id == vehicle_id)
                .where(FuelLog.odometer_km.is_not(None))
                .order_by(FuelLog.id.desc()).limit(5)
            ))
        if len(rows) < 2:
            return
        # rows is id-desc: rows[0]=newest fill, rows[-1]=oldest. The km
        # span we measure is (newest_km - oldest_km), so the liters used
        # to traverse it are all fills *during* the span — every fill
        # except the oldest tank which fed the trip BEFORE our oldest
        # km reading. In DESC order that's rows[:-1].
        liters_between = sum(r.liters for r in rows[:-1])
        km_between = rows[0].odometer_km - rows[-1].odometer_km
        if km_between <= 0:
            return
        factual = round(liters_between / km_between * 100, 2)
        if 4 <= factual <= 25:  # sanity
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(Vehicle).where(Vehicle.id == vehicle_id).values(
                        factual_l_100=factual, updated_at=iso_now(),
                    )
                )
            log.info("factual_consumption_updated", l_100=factual)

    # ─── vehicle state ────────────────────────────────────────────────

    async def _vehicle_status(self) -> dict:
        v = await self._get_or_create_default_vehicle()
        return {
            "name": v.name, "year": v.year, "fuel": v.fuel_type,
            "tank_l": v.tank_l, "tank_remaining_l": v.tank_remaining_l,
            "odometer_km": v.odometer_km,
            "avg_city_l_100": v.avg_city_l_100,
            "avg_highway_l_100": v.avg_highway_l_100,
            "factual_l_100": v.factual_l_100,
        }

    async def _set_vehicle(self, p: dict) -> dict:
        v = await self._get_or_create_default_vehicle()
        values = {k: p[k] for k in (
            "odometer_km", "tank_remaining_l", "avg_city_l_100", "avg_highway_l_100",
        ) if k in p}
        if not values:
            return {"error": "Нечего обновлять"}
        values["updated_at"] = iso_now()
        async with self._memory._engine.begin() as conn:
            await conn.execute(sql_update(Vehicle).where(Vehicle.id == v.id).values(**values))
        return {"updated": values}

    async def _list_trips(self) -> dict:
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(Trip).where(Trip.status.in_(("planned", "active")))
                .order_by(Trip.depart_at.asc()).limit(10)
            ))
        return {"trips": [
            {"id": r.id, "origin": r.origin, "destination": r.destination,
             "depart_at": r.depart_at, "distance_km": r.distance_km,
             "duration_min": r.duration_min, "fuel_l": r.fuel_estimate_l,
             "status": r.status}
            for r in rows
        ]}

    # ─── helpers ──────────────────────────────────────────────────────

    # ─── alerts / weather / checklist ─────────────────────────────────

    async def _check_alerts_for_regions(self, regions: list[str]) -> list[str]:
        """Cross-check active air alerts and recent strike posts against
        the oblasts the route passes through."""
        if not regions:
            return []
        from datetime import timedelta
        from src.db.models import ActiveAlert, NewsPost
        warnings: list[str] = []
        async with self._memory._engine.connect() as conn:
            actives = list(await conn.execute(select(ActiveAlert)))
            cutoff = (now_kyiv() - timedelta(hours=24)).isoformat()
            recent_alerts = list(await conn.execute(
                select(NewsPost).where(NewsPost.is_alert == 1)
                .where(NewsPost.date >= cutoff)
            ))
        regions_lc = [r.lower() for r in regions]
        for a in actives:
            r = (a.region or "").lower()
            if any(reg in r or r in reg for reg in regions_lc):
                warnings.append(f"🚨 Активная тревога: {a.region}. Подожди отбоя.")
        strike_regions: set[str] = set()
        for n in recent_alerts:
            r = (getattr(n, "alert_region", "") or "").lower()
            if not r:
                continue
            if any(reg in r or r in reg for reg in regions_lc):
                strike_regions.add(r)
        if strike_regions:
            warnings.append(
                "⚠️ За сутки фиксировались тревоги по маршруту: "
                + ", ".join(sorted(strike_regions))
            )
        return warnings

    async def _weather_at_arrival(
        self, destination: str, depart_dt: datetime, duration_min: int,
    ) -> dict:
        try:
            from datetime import timedelta
            from src.config import get_settings
            from src.integrations.weather import WeatherClient
            client = WeatherClient.from_settings(get_settings())
            if not client:
                return {}
            # rough hour offset
            arrival_dt = depart_dt + timedelta(minutes=duration_min)
            # OpenWeather/Open-Meteo: forecast() returns list per hour
            hourly_count = max(1, min(72, int((arrival_dt - now_kyiv()).total_seconds() // 3600) + 2))
            # Use destination city — strip after first comma
            city = destination.split(",")[0].strip()
            forecast = await client.forecast(city=city, hours=hourly_count)
            target_iso = arrival_dt.strftime("%Y-%m-%dT%H:00")
            # Find slot closest to arrival
            best = None
            best_diff = 1e9
            for h in forecast:
                t = h.get("time") or ""
                if not t:
                    continue
                try:
                    diff = abs((datetime.fromisoformat(t.replace("Z", "")) - arrival_dt).total_seconds())
                except Exception:
                    continue
                if diff < best_diff:
                    best, best_diff = h, diff
            if not best:
                return {}
            return {
                "city": city,
                "at": arrival_dt.isoformat(),
                "temp_c": best.get("temp_c"),
                "description": best.get("description"),
                "rain_mm": best.get("rain_mm"),
                "wind_ms": best.get("wind_ms"),
            }
        except Exception:
            log.exception("weather_at_arrival_failed")
            return {}

    def _build_checklist(
        self, distance_km: float, duration_min: int,
        arrival_weather: dict, notes: str,
    ) -> list[str]:
        items = [
            "тех. паспорт + страховка",
            "права + военный билет",
            "ключи, телефон, павербанк",
        ]
        if duration_min >= 180:
            items.append("термос/вода + перекус")
            items.append("зарядка в авто, наушники")
        if distance_km >= 300:
            items.append("запас топлива в плане (см. АЗС по маршруту)")
        if arrival_weather:
            t = arrival_weather.get("temp_c")
            rain = arrival_weather.get("rain_mm") or 0
            if rain and rain > 0.3:
                items.append("☂️ зонт — в точке прибытия дождь")
            if t is not None:
                if t < 0:
                    items.append("🧥 тёплая куртка/перчатки — на месте мороз")
                elif t < 10:
                    items.append("куртка — на месте прохладно")
                elif t > 26:
                    items.append("😎 очки/вода — на месте жарко")
        if "матвей" in notes.lower() or "малыш" in notes.lower() or "ребен" in notes.lower():
            items.append("🤱 подгузники, смесь, бутылочка, плед, аптечка малыша")
            items.append("автокресло проверить крепление")
        return items

    # ─── trip arming ──────────────────────────────────────────────────

    def _arm_trip_jobs(
        self, trip_id: int, depart_dt: datetime, return_at: str | None,
    ) -> dict:
        scheduler = getattr(self, "_scheduler", None)
        if not scheduler:
            return {"armed": False, "reason": "no_scheduler"}
        from datetime import timedelta
        # 1. Pre-trip push: 30 minutes before departure
        pre = depart_dt - timedelta(minutes=30)
        if pre > now_kyiv():
            scheduler.add_job(
                self._pre_trip_push, "date", run_date=pre,
                args=[trip_id], id=f"trip_{trip_id}_pre", replace_existing=True,
            )
        # 2. Trip-mode ON at departure (turn off non-essential devices)
        scheduler.add_job(
            self._enter_trip_mode, "date", run_date=depart_dt,
            args=[trip_id], id=f"trip_{trip_id}_arm", replace_existing=True,
        )
        # 3. Trip-mode OFF at return (turn devices back on)
        if return_at:
            try:
                from src.utils.time import KYIV_TZ
                ret = datetime.fromisoformat(return_at)
                if ret.tzinfo is None:
                    ret = ret.replace(tzinfo=KYIV_TZ)
                scheduler.add_job(
                    self._exit_trip_mode, "date", run_date=ret,
                    args=[trip_id], id=f"trip_{trip_id}_disarm", replace_existing=True,
                )
            except Exception:
                log.exception("trip_disarm_parse_failed")
        return {"armed": True, "pre_push_at": pre.isoformat(), "departure": depart_dt.isoformat()}

    _TRIP_MODE_DEVICES_OFF = ("бойлер",)

    async def _enter_trip_mode(self, trip_id: int) -> None:
        try:
            from sqlalchemy import insert as sql_insert
            from src.db.models import FamilyMode
            async with self._memory._engine.begin() as conn:
                await conn.execute(sql_insert(FamilyMode).prefix_with("OR REPLACE").values(
                    name="trip", enabled=1, payload=str(trip_id),
                    started_at=iso_now(), expires_at=None,
                ))
            # Turn off non-essentials via Tuya
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            t = TuyaClient.from_settings(get_settings())
            if t:
                for dev in self._TRIP_MODE_DEVICES_OFF:
                    try:
                        await t.control(dev, "off")
                    except Exception:
                        log.exception("trip_off_failed", device=dev)
            await self.send(f"🧭 Trip-mode включен. Бойлер выкл, экономим. Поездка #{trip_id} в работе.")
        except Exception:
            log.exception("enter_trip_mode_failed")

    async def _exit_trip_mode(self, trip_id: int) -> None:
        try:
            from sqlalchemy import insert as sql_insert
            from src.db.models import FamilyMode
            async with self._memory._engine.begin() as conn:
                await conn.execute(sql_insert(FamilyMode).prefix_with("OR REPLACE").values(
                    name="trip", enabled=0, payload=str(trip_id),
                    started_at=iso_now(), expires_at=iso_now(),
                ))
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            t = TuyaClient.from_settings(get_settings())
            if t:
                for dev in self._TRIP_MODE_DEVICES_OFF:
                    try:
                        await t.control(dev, "on")
                    except Exception:
                        log.exception("trip_on_failed", device=dev)
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(Trip).where(Trip.id == trip_id).values(status="done")
                )
            await self.send(f"🧭 С возвращением! Trip-mode выключен, бойлер обратно. Поездка #{trip_id} закрыта.")
        except Exception:
            log.exception("exit_trip_mode_failed")

    async def _pre_trip_push(self, trip_id: int) -> None:
        try:
            async with self._memory._engine.connect() as conn:
                trip = (await conn.execute(select(Trip).where(Trip.id == trip_id))).first()
            if not trip:
                return
            summary = json.loads(trip.route_summary or "{}")
            stations = summary.get("stations", [])[:3]
            warnings = summary.get("alert_warnings") or []
            checklist = summary.get("checklist") or []
            arr = summary.get("arrival_weather") or {}
            text_lines = [
                f"🧭 <b>Через 30 минут выезжать</b> в {trip.destination}",
                f"📍 {trip.origin} → {trip.destination}",
                f"🛣 {trip.distance_km} км · ⏱ ~{(trip.duration_min or 0)//60}ч {(trip.duration_min or 0)%60}м с пробками",
                f"⛽ Расход ~{trip.fuel_estimate_l}л (~{int(trip.fuel_estimate_uah or 0)}₴)",
            ]
            if arr and arr.get("temp_c") is not None:
                text_lines.append(
                    f"☁️ В {arr.get('city')}: {arr['temp_c']:+.0f}°, {arr.get('description') or ''}"
                )
            if warnings:
                text_lines.append("\n<b>⚠️ По маршруту</b>")
                text_lines.extend(warnings)
            if stations:
                text_lines.append("\n<b>⛽ АЗС в приоритете</b>")
                for s in stations:
                    text_lines.append(f"• {s.get('name')} — {s.get('address', '')}")
            if checklist:
                text_lines.append("\n<b>📋 Чек-лист</b>")
                for it in checklist:
                    text_lines.append(f"• {it}")
            await self.send("\n".join(text_lines))
        except Exception:
            log.exception("pre_trip_push_failed")

    async def _last_fuel_price(self, vehicle_id: int) -> float | None:
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(
                select(FuelLog).where(FuelLog.vehicle_id == vehicle_id)
                .where(FuelLog.price_per_l.is_not(None))
                .order_by(FuelLog.id.desc()).limit(1)
            )).first()
        return row.price_per_l if row else None

    async def _get_or_create_default_vehicle(self) -> Vehicle:
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(select(Vehicle).limit(1))).first()
        if row:
            return row
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(Vehicle).values(
                name="Dodge Dart",
                make="Dodge", model="Dart", year=2015,
                engine_l=2.5, fuel_type="бензин",
                tank_l=60.0,
                avg_city_l_100=11.5, avg_highway_l_100=9.5,
                odometer_km=0.0, tank_remaining_l=0.0,
                created_at=iso_now(), updated_at=iso_now(),
            ))
            row = (await conn.execute(select(Vehicle).limit(1))).first()
        return row


def _extract_json(text: str) -> dict:
    import re
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}
