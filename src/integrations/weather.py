"""Weather: OpenWeatherMap primary, Open-Meteo fallback (no key needed).

If OPENWEATHER_API_KEY is missing or invalid, automatically falls back to
Open-Meteo (https://open-meteo.com — free, no auth, no daily limit).
"""
from __future__ import annotations

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_BASE = "https://api.openweathermap.org/data/2.5"

# Hardcoded coords for common cities — used by Open-Meteo fallback
_CITY_COORDS = {
    "odesa": (46.4825, 30.7233),
    "одеса": (46.4825, 30.7233),
    "одесса": (46.4825, 30.7233),
    "kyiv": (50.4501, 30.5234),
    "київ": (50.4501, 30.5234),
    "киев": (50.4501, 30.5234),
    "lviv": (49.8397, 24.0297),
    "львов": (49.8397, 24.0297),
    "kharkiv": (49.9935, 36.2304),
    "харьков": (49.9935, 36.2304),
}


def _resolve_coords(city: str) -> tuple[float, float]:
    """Try hardcoded list, fall back to Odesa."""
    key = (city or "").split(",")[0].strip().lower()
    return _CITY_COORDS.get(key, _CITY_COORDS["odesa"])


class WeatherClient:
    def __init__(self, api_key: str = "", default_city: str = "Odesa,UA", lang: str = "ru") -> None:
        self.api_key = api_key
        self.default_city = default_city
        self.lang = lang

    @classmethod
    def from_settings(cls, settings: Any) -> "WeatherClient | None":
        key = getattr(settings, "openweather_api_key", "")
        # Always return a client now — even without OpenWeather, fallback works
        from src.utils.family import _current_location, LOCATION
        loc = _current_location() or LOCATION
        country = "UA" if loc.get("country", "").lower().startswith("укр") else ""
        city = loc.get("city", "Odesa")
        if country:
            city = f"{city},{country}"
        return cls(key, default_city=city)

    async def _get(self, path: str, params: dict) -> dict:
        params = {**params, "appid": self.api_key, "lang": self.lang, "units": "metric"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{_BASE}{path}", params=params) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"OpenWeather {path}: HTTP {resp.status}: {text[:200]}")
                return await resp.json()

    async def current(self, city: str | None = None) -> dict:
        target_city = city or self.default_city
        # Try OpenWeather first if key is present
        if self.api_key:
            try:
                data = await self._get("/weather", {"q": target_city})
                main = data.get("main", {})
                weather = (data.get("weather") or [{}])[0]
                wind = data.get("wind", {})
                return {
                    "source": "openweather",
                    "city": data.get("name") or target_city,
                    "description": weather.get("description", "").capitalize(),
                    "icon": weather.get("icon"),
                    "temp_c": round(main.get("temp", 0), 1),
                    "feels_like_c": round(main.get("feels_like", 0), 1),
                    "humidity_pct": main.get("humidity"),
                    "pressure_mb": main.get("pressure"),
                    "wind_ms": round(wind.get("speed", 0), 1),
                    "clouds_pct": (data.get("clouds") or {}).get("all"),
                    "visibility_km": round((data.get("visibility") or 0) / 1000, 1),
                }
            except Exception as e:
                log.warning("openweather_failed_fallback_to_meteo", error=str(e))
        # Fallback: Open-Meteo (no key)
        return await self._current_open_meteo(target_city)

    async def _current_open_meteo(self, city: str) -> dict:
        lat, lon = _resolve_coords(city)
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "precipitation,weather_code,wind_speed_10m,cloud_cover,pressure_msl",
            "timezone": "Europe/Kyiv",
            "wind_speed_unit": "ms",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Open-Meteo HTTP {resp.status}")
                data = await resp.json()
        cur = data.get("current", {}) or {}
        return {
            "source": "open-meteo",
            "city": city,
            "description": _weather_code_to_text(cur.get("weather_code")),
            "temp_c": round(cur.get("temperature_2m", 0), 1),
            "feels_like_c": round(cur.get("apparent_temperature", 0), 1),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "pressure_mb": cur.get("pressure_msl"),
            "wind_ms": round(cur.get("wind_speed_10m", 0), 1),
            "clouds_pct": cur.get("cloud_cover"),
            "precipitation_mm": cur.get("precipitation"),
        }

    async def forecast(self, city: str | None = None, hours: int = 24) -> list[dict]:
        target_city = city or self.default_city
        if self.api_key:
            try:
                data = await self._get("/forecast", {"q": target_city})
                items = data.get("list", []) or []
                max_items = max(1, min(hours // 3, len(items)))
                out = []
                for it in items[:max_items]:
                    main = it.get("main", {})
                    weather = (it.get("weather") or [{}])[0]
                    out.append({
                        "time": it.get("dt_txt"),
                        "temp_c": round(main.get("temp", 0), 1),
                        "humidity_pct": main.get("humidity"),
                        "description": weather.get("description", "").capitalize(),
                        "wind_ms": round((it.get("wind") or {}).get("speed", 0), 1),
                        "rain_mm": (it.get("rain") or {}).get("3h", 0),
                        "pop_pct": int((it.get("pop") or 0) * 100),
                    })
                return out
            except Exception as e:
                log.warning("openweather_forecast_failed_fallback", error=str(e))
        return await self._forecast_open_meteo(target_city, hours)

    async def _forecast_open_meteo(self, city: str, hours: int) -> list[dict]:
        lat, lon = _resolve_coords(city)
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": "temperature_2m,relative_humidity_2m,weather_code,"
                      "wind_speed_10m,precipitation,precipitation_probability",
            "timezone": "Europe/Kyiv",
            "wind_speed_unit": "ms",
            "forecast_days": min(7, max(1, (hours // 24) + 1)),
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Open-Meteo HTTP {resp.status}")
                data = await resp.json()
        h = data.get("hourly", {}) or {}
        times = h.get("time", [])
        out = []
        max_items = min(hours, len(times))
        for i in range(max_items):
            out.append({
                "time": times[i],
                "temp_c": h.get("temperature_2m", [None])[i],
                "humidity_pct": h.get("relative_humidity_2m", [None])[i],
                "description": _weather_code_to_text(h.get("weather_code", [None])[i]),
                "wind_ms": h.get("wind_speed_10m", [None])[i],
                "rain_mm": h.get("precipitation", [None])[i] or 0,
                "pop_pct": h.get("precipitation_probability", [None])[i] or 0,
            })
        return out


def _weather_code_to_text(code) -> str:
    if code is None:
        return ""
    code = int(code)
    return {
        0: "Ясно", 1: "Преимущественно ясно", 2: "Переменная облачность",
        3: "Пасмурно", 45: "Туман", 48: "Иней",
        51: "Морось слабая", 53: "Морось", 55: "Морось сильная",
        61: "Дождь слабый", 63: "Дождь", 65: "Дождь сильный",
        66: "Ледяной дождь", 67: "Ледяной дождь сильный",
        71: "Снег слабый", 73: "Снег", 75: "Снег сильный",
        77: "Снежные зёрна",
        80: "Ливни слабые", 81: "Ливни", 82: "Ливни сильные",
        85: "Снегопад слабый", 86: "Снегопад сильный",
        95: "Гроза", 96: "Гроза с градом", 99: "Гроза сильная с градом",
    }.get(code, f"Погодный код {code}")
