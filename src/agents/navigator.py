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
        return await super()._call_tool(tool_name, tool_input)

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
                }, ensure_ascii=False),
                status="planned",
                notes=p.get("notes"),
                created_at=iso_now(),
            ))
            trip_id = result.inserted_primary_key[0] if result.inserted_primary_key else None

        eta_min = route["duration_traffic_min"] or route["duration_min"]
        eta_h, eta_m = divmod(eta_min, 60)
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
            "stations_top": [
                {"name": s["name"], "address": s["address"]} for s in top_stations
            ],
            "display_instruction": (
                "Покажи юзеру: маршрут, ETA, расход, оценку стоимости топлива, "
                "топ-5 приоритетных АЗС (Укрнафта первой если есть), "
                "и спроси нужно ли активировать trip-mode у Прораба."
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

        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(FuelLog).values(
                vehicle_id=vehicle.id,
                station=parsed.get("station"),
                liters=float(liters),
                price_per_l=parsed.get("price_per_l"),
                total_uah=parsed.get("total_uah"),
                odometer_km=odometer_km,
                fuel_kind=parsed.get("fuel_kind"),
                receipt_path=image_path,
                created_at=iso_now(),
            ))
        # Refresh factual_l_100 from last two fills if odometer available
        await self._maybe_update_factual_consumption(vehicle.id)
        return {"saved": True, "parsed": parsed}

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
        # Newest - previous: liters_used between fills
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
