"""Nova Poshta tracking integration.

Free public API for parcel status by TTN (track number).
API key: register at https://novaposhta.ua/private/ → API → Get key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_API_URL = "https://api.novaposhta.ua/v2.0/json/"


class NovaPoshtaAuthError(Exception):
    """TokenOAuth2 (personal-cabinet session token) is missing, invalid, or
    expired — getIncomingDocumentsByPhone answered success=false. NP doesn't
    document this method or its failure shape, so this is a best-effort
    signal, not a confirmed error code: any non-success response from this
    call is treated as "token needs refreshing"."""


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

    async def list_incoming_by_phone(
        self, oauth_token: str, date_from: datetime, date_to: datetime,
        page: int = 1, limit: int = 100,
    ) -> list[dict]:
        """Auto-discover INCOMING parcels (recipient side) — the thing the
        public API/apiKey can never do (see git history: getDocumentList,
        getStatusDocumentsByPhone and getCounterpartyContactPersons were all
        tried against the public key and only ever return outgoing/nothing).

        This calls the same endpoint but reverse-engineered from
        my.novaposhta.ua's own web traffic: auth is a `TokenOAuth2` header
        carrying the personal cabinet's web-session token (NOT the apiKey
        body field), and the method itself — `getIncomingDocumentsByPhone`
        — is undocumented and private to that cabinet frontend. The session
        behind this token is long-lived (weeks), so a family member copies
        it by hand from DevTools once in a while (NOVA_POSHTA_TOKEN_OAUTH2)
        rather than this needing a full login flow.

        Unofficial: Nova Poshta can change or break this at any time.
        """
        body = {
            "system": "PA 3.0",
            "modelName": "InternetDocument",
            "calledMethod": "getIncomingDocumentsByPhone",
            "methodProperties": {
                "DateFrom": date_from.strftime("%d.%m.%Y %H:%M:%S"),
                "DateTo": date_to.strftime("%d.%m.%Y %H:%M:%S"),
                "Page": page,
                "Limit": limit,
                "SearchByCounterparties": None,
                "iCounterparties": None,
            },
        }
        headers = {"Content-Type": "application/json", "TokenOAuth2": oauth_token}
        async with aiohttp.ClientSession() as session:
            async with session.post(_API_URL, json=body, headers=headers) as resp:
                data = await resp.json()
        if not data.get("success"):
            raise NovaPoshtaAuthError(str(data.get("errors") or "unknown"))
        out: list[dict] = []
        for group in data.get("data", []) or []:
            if isinstance(group, dict):
                out.extend(group.get("result") or [])
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
