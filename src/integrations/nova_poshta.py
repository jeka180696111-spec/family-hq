"""Nova Poshta tracking integration.

Free public API for parcel status by TTN (track number).
API key: register at https://novaposhta.ua/private/ → API → Get key.
"""
from __future__ import annotations

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_API_URL = "https://api.novaposhta.ua/v2.0/json/"


class NovaPoshtaClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_settings(cls, settings: Any) -> "NovaPoshtaClient | None":
        key = getattr(settings, "nova_poshta_api_key", "")
        return cls(key) if key else None

    async def track(self, ttn: str, phone_last4: str = "") -> dict:
        """Return current parcel status. Phone is optional (helps unlock more info)."""
        body = {
            "apiKey": self.api_key,
            "modelName": "TrackingDocumentGeneral",
            "calledMethod": "getStatusDocuments",
            "methodProperties": {
                "Documents": [{"DocumentNumber": ttn, "Phone": phone_last4 or ""}],
            },
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(_API_URL, json=body) as resp:
                data = await resp.json()
        if not data.get("success") or not data.get("data"):
            return {"error": data.get("errors", ["unknown"])[0] if data.get("errors") else "no data"}
        d = data["data"][0]
        return {
            "ttn": ttn,
            "status": d.get("Status", ""),
            "status_code": d.get("StatusCode"),
            "city_from": d.get("CitySender", ""),
            "city_to": d.get("CityRecipient", ""),
            "warehouse": d.get("WarehouseRecipient", ""),
            "weight_kg": d.get("DocumentWeight"),
            "cost_uah": d.get("DocumentCost"),
            "scheduled_at": d.get("ScheduledDeliveryDate"),
            "actual_delivery": d.get("ActualDeliveryDate"),
            "tracking_url": f"https://novaposhta.ua/tracking/?cargo_number={ttn}",
        }

    async def track_many(self, ttns: list[str]) -> list[dict]:
        out = []
        for t in ttns:
            try:
                out.append(await self.track(t))
            except Exception:
                log.exception("nova_track_failed", ttn=t)
        return out
