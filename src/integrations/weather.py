"""Weather integration via OpenWeatherMap (free tier: 1000 calls/day).

Setup:
  1. https://openweathermap.org/api → sign up (free)
  2. API Keys tab → copy key (активуется через ~10 минут)
  3. Railway env: OPENWEATHER_API_KEY=<key>
"""
from __future__ import annotations

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_BASE = "https://api.openweathermap.org/data/2.5"


class WeatherClient:
    def __init__(self, api_key: str, default_city: str = "Odesa,UA", lang: str = "ru") -> None:
        self.api_key = api_key
        self.default_city = default_city
        self.lang = lang

    @classmethod
    def from_settings(cls, settings: Any) -> "WeatherClient | None":
        key = getattr(settings, "openweather_api_key", "")
        if not key:
            return None
        # Default city — use family location
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
        data = await self._get("/weather", {"q": city or self.default_city})
        main = data.get("main", {})
        weather = (data.get("weather") or [{}])[0]
        wind = data.get("wind", {})
        return {
            "city": data.get("name") or city,
            "description": weather.get("description", "").capitalize(),
            "icon": weather.get("icon"),
            "temp_c": round(main.get("temp", 0), 1),
            "feels_like_c": round(main.get("feels_like", 0), 1),
            "humidity_pct": main.get("humidity"),
            "pressure_mb": main.get("pressure"),
            "wind_ms": round(wind.get("speed", 0), 1),
            "wind_deg": wind.get("deg"),
            "clouds_pct": (data.get("clouds") or {}).get("all"),
            "visibility_km": round((data.get("visibility") or 0) / 1000, 1),
        }

    async def forecast(self, city: str | None = None, hours: int = 24) -> list[dict]:
        """3-hour-step forecast for the next N hours (max 120)."""
        data = await self._get("/forecast", {"q": city or self.default_city})
        items = data.get("list", []) or []
        max_items = max(1, min(hours // 3, len(items)))
        out = []
        for it in items[:max_items]:
            main = it.get("main", {})
            weather = (it.get("weather") or [{}])[0]
            out.append({
                "time": it.get("dt_txt"),
                "temp_c": round(main.get("temp", 0), 1),
                "feels_like_c": round(main.get("feels_like", 0), 1),
                "humidity_pct": main.get("humidity"),
                "description": weather.get("description", "").capitalize(),
                "wind_ms": round((it.get("wind") or {}).get("speed", 0), 1),
                "rain_mm": (it.get("rain") or {}).get("3h", 0),
                "snow_mm": (it.get("snow") or {}).get("3h", 0),
                "pop_pct": int((it.get("pop") or 0) * 100),  # probability of precipitation
            })
        return out
