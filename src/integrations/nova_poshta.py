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
        # Money fields: NP separates shipping cost from cash-on-delivery
        # (післяплата / наложенный платёж). Total = shipping + cod.
        def _money(*keys: str) -> float | None:
            for k in keys:
                v = d.get(k)
                if v is None or v == "":
                    continue
                try:
                    fv = float(v)
                    if fv:
                        return fv
                except (TypeError, ValueError):
                    continue
            return None

        shipping = _money("DocumentCost")
        # Наложенный платёж — берем первую непустую сумму из вариантов
        cod = _money(
            "AfterpaymentOnGoodsCost",   # сумма к оплате при получении
            "BackwardDeliveryMoney",      # возвратная сумма
            "BackwardDeliverySum",
            "RedeliverySum",
        )
        total = (shipping or 0) + (cod or 0) if (shipping or cod) else None

        return {
            "ttn": ttn,
            "status": d.get("Status", ""),
            "status_code": d.get("StatusCode"),
            "city_from": d.get("CitySender", ""),
            "city_to": d.get("CityRecipient", ""),
            "warehouse": d.get("WarehouseRecipient", ""),
            "weight_kg": d.get("DocumentWeight"),
            "shipping_uah": shipping,        # стоимость доставки
            "cod_uah": cod,                  # наложенный платёж
            "total_uah": total,              # общая сумма
            "cost_uah": shipping,            # legacy alias
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

    async def _unused_try_list_incoming(self, days_back: int = 30) -> list[dict]:
        """Experimental: try several method variants to retrieve INCOMING
        parcels (where the key holder is the recipient). Returns first
        non-empty result. NP has no documented incoming endpoint, but
        with the mobile-app key, some private methods may respond."""
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=days_back)
        date_from = start.strftime("%d.%m.%Y")
        date_to = end.strftime("%d.%m.%Y")

        attempts = [
            # 1) Same getDocumentList but explicit empty SenderRef + GetFullList
            {
                "modelName": "InternetDocument",
                "calledMethod": "getDocumentList",
                "methodProperties": {
                    "DateTimeFrom": date_from, "DateTimeTo": date_to,
                    "GetFullList": "1", "Page": "1",
                },
            },
            # 2) Tracking by phone (some NP variants accept this)
            {
                "modelName": "TrackingDocumentGeneral",
                "calledMethod": "getStatusDocumentsByPhone",
                "methodProperties": {},
            },
            # 3) Counterparty: list of parcels where I'm the recipient
            {
                "modelName": "Counterparty",
                "calledMethod": "getCounterpartyContactPersons",
                "methodProperties": {"Ref": "", "Page": "1"},
            },
        ]

        out: list[dict] = []
        async with aiohttp.ClientSession() as session:
            for body in attempts:
                payload = {"apiKey": self.api_key, **body}
                try:
                    async with session.post(_API_URL, json=payload) as resp:
                        data = await resp.json()
                except Exception:
                    log.exception("nova_incoming_attempt_failed",
                                  method=body["calledMethod"])
                    continue
                if data.get("success") and data.get("data"):
                    log.info("nova_incoming_attempt_ok",
                             method=body["calledMethod"], rows=len(data["data"]))
                    for d in data["data"]:
                        if not isinstance(d, dict):
                            continue
                        out.append({
                            "ttn": d.get("IntDocNumber") or d.get("Number") or d.get("DocNumber"),
                            "description": d.get("Description"),
                            "state": d.get("StateName") or d.get("Status"),
                            "raw_method": body["calledMethod"],
                        })
                    if out:
                        return out
                else:
                    log.info("nova_incoming_attempt_empty",
                             method=body["calledMethod"],
                             errors=data.get("errors") or data.get("warnings"))
        return out

    async def list_recent_documents(self, days_back: int = 14) -> list[dict]:
        """Return TTNs the account holder is involved in (sender side).

        Used to auto-discover new parcels — once an hour we check and
        any TTN we haven't seen gets tracked + announced.
        """
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=days_back)
        body = {
            "apiKey": self.api_key,
            "modelName": "InternetDocument",
            "calledMethod": "getDocumentList",
            "methodProperties": {
                "DateTimeFrom": start.strftime("%d.%m.%Y"),
                "DateTimeTo": end.strftime("%d.%m.%Y"),
                "Page": "1",
                "GetFullList": "1",
            },
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(_API_URL, json=body) as resp:
                    data = await resp.json()
        except Exception:
            log.exception("nova_list_documents_failed")
            return []
        if not data.get("success"):
            return []
        out = []
        for d in data.get("data", []) or []:
            out.append({
                "ttn": d.get("IntDocNumber") or d.get("Number"),
                "ref": d.get("Ref"),
                "description": d.get("Description"),
                "sender_city": d.get("CitySender"),
                "recipient_city": d.get("CityRecipient"),
                "cost_uah": d.get("Cost"),
                "weight_kg": d.get("Weight"),
                "created_at": d.get("DateTime"),
                "scheduled_at": d.get("ScheduledDeliveryDate"),
                "state": d.get("StateName"),
            })
        return out
