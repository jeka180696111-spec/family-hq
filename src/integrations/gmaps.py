"""Google Maps integration: Directions + Places (gas stations).

Uses one API key with these APIs enabled in GCP:
  - Directions API
  - Places API (New) — text search / nearby search

Free tier ($200/mo) covers a family-scale use comfortably.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()


_STATION_PRIORITY = ("укрнафта", "ukrnafta", "wog", "okko", "socar", "upg", "shell", "anp", "klo")


class GMapsClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_settings(cls, settings: Any) -> "GMapsClient | None":
        key = getattr(settings, "gmaps_api_key", None)
        return cls(key) if key else None

    # ─── Directions ──────────────────────────────────────────────────

    async def directions(
        self, origin: str, destination: str, depart_at: datetime | None = None,
    ) -> dict:
        """Get route with traffic-aware ETA.

        Returns: {distance_km, duration_min, duration_traffic_min,
                  polyline, summary, warnings, steps, bbox, waypoints_latlng}
        """
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": origin,
            "destination": destination,
            "mode": "driving",
            "language": "uk",
            "region": "ua",
            "alternatives": "false",
            "key": self.api_key,
        }
        if depart_at:
            # Google wants seconds since epoch; "now" gives current traffic
            ts = int(depart_at.timestamp())
            params["departure_time"] = str(ts) if depart_at > datetime.now(depart_at.tzinfo) else "now"
            params["traffic_model"] = "best_guess"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
        if data.get("status") != "OK":
            raise RuntimeError(f"Directions API: {data.get('status')} {data.get('error_message', '')}")
        route = data["routes"][0]
        leg = route["legs"][0]
        steps = leg.get("steps", [])
        # Sample waypoints along the route (every ~50km) for downstream lookups
        waypoints = []
        accum_km = 0.0
        sample_every_km = 50.0
        next_target = sample_every_km
        for step in steps:
            d_km = (step.get("distance", {}).get("value", 0) or 0) / 1000
            accum_km += d_km
            if accum_km >= next_target:
                loc = step.get("end_location", {})
                waypoints.append((loc.get("lat"), loc.get("lng")))
                next_target += sample_every_km
        # Always include start + end
        start_loc = leg["start_location"]
        end_loc = leg["end_location"]
        waypoints = [(start_loc["lat"], start_loc["lng"]), *waypoints, (end_loc["lat"], end_loc["lng"])]
        return {
            "distance_km": round((leg.get("distance", {}).get("value", 0) or 0) / 1000, 1),
            "duration_min": int((leg.get("duration", {}).get("value", 0) or 0) / 60),
            "duration_traffic_min": int((leg.get("duration_in_traffic", {}).get("value", 0) or 0) / 60) or None,
            "summary": route.get("summary", ""),
            "warnings": route.get("warnings", []) or [],
            "polyline": route.get("overview_polyline", {}).get("points", ""),
            "start_address": leg.get("start_address", ""),
            "end_address": leg.get("end_address", ""),
            "waypoints_latlng": waypoints,
        }

    # ─── Places: gas stations ─────────────────────────────────────────

    async def reverse_geocode_regions(
        self, waypoints: list[tuple[float, float]],
    ) -> list[str]:
        """Return de-duplicated list of administrative_area_level_1 names
        (oblast in UA) for each waypoint. Used to cross-check active alerts."""
        regions: list[str] = []
        seen: set[str] = set()
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        async with aiohttp.ClientSession() as session:
            for (lat, lng) in waypoints:
                if lat is None or lng is None:
                    continue
                params = {
                    "latlng": f"{lat},{lng}", "language": "uk",
                    "result_type": "administrative_area_level_1",
                    "key": self.api_key,
                }
                try:
                    async with session.get(url, params=params) as resp:
                        data = await resp.json()
                except Exception:
                    continue
                if data.get("status") != "OK":
                    continue
                for r in data.get("results", []) or []:
                    for c in r.get("address_components", []) or []:
                        if "administrative_area_level_1" in (c.get("types") or []):
                            nm = (c.get("long_name") or "").lower().replace(" область", "").strip()
                            if nm and nm not in seen:
                                seen.add(nm)
                                regions.append(nm)
        return regions

    async def gas_stations_along_route(
        self, waypoints: list[tuple[float, float]], radius_m: int = 3000,
        max_per_point: int = 5,
    ) -> list[dict]:
        """Find gas stations near each waypoint. Deduplicate, prioritize."""
        all_stations: dict[str, dict] = {}
        async with aiohttp.ClientSession() as session:
            for (lat, lng) in waypoints:
                if lat is None or lng is None:
                    continue
                stations = await self._nearby_gas(session, lat, lng, radius_m, max_per_point)
                for s in stations:
                    key = s.get("place_id") or f"{s.get('name')}_{s.get('lat')}_{s.get('lng')}"
                    if key not in all_stations:
                        all_stations[key] = s
        ranked = sorted(all_stations.values(), key=lambda s: _station_rank(s.get("name", "")))
        return ranked

    async def _nearby_gas(
        self, session: aiohttp.ClientSession, lat: float, lng: float,
        radius_m: int, limit: int,
    ) -> list[dict]:
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            "location": f"{lat},{lng}",
            "radius": str(radius_m),
            "type": "gas_station",
            "language": "uk",
            "key": self.api_key,
        }
        try:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
            if data.get("status") not in ("OK", "ZERO_RESULTS"):
                log.warning("places_nearby_failed", status=data.get("status"))
                return []
            results = data.get("results", []) or []
            out = []
            for r in results[:limit]:
                loc = (r.get("geometry") or {}).get("location") or {}
                out.append({
                    "place_id": r.get("place_id"),
                    "name": r.get("name", ""),
                    "address": r.get("vicinity", ""),
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                    "open_now": (r.get("opening_hours") or {}).get("open_now"),
                    "rating": r.get("rating"),
                })
            return out
        except Exception:
            log.exception("places_nearby_error")
            return []


def _station_rank(name: str) -> int:
    n = name.lower()
    for i, brand in enumerate(_STATION_PRIORITY):
        if brand in n:
            return i
    return len(_STATION_PRIORITY)
