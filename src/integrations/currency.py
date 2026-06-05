"""Currency rates from National Bank of Ukraine (no API key required)."""
from __future__ import annotations

from datetime import date
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_NBU_BASE = "https://bank.gov.ua/NBUStatService/v1/statdirectory"


class NBUClient:
    """Free NBU public API. Returns rates in UAH per 1 unit of currency."""

    async def rates(self, currencies: list[str] | None = None, on_date: date | None = None) -> list[dict]:
        params: dict[str, Any] = {"json": ""}
        if on_date:
            params["date"] = on_date.strftime("%Y%m%d")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{_NBU_BASE}/exchange", params=params) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"NBU HTTP {resp.status}")
                data = await resp.json()
        if currencies:
            wanted = {c.upper() for c in currencies}
            data = [r for r in data if (r.get("cc") or "").upper() in wanted]
        return [
            {
                "code": r.get("cc"),
                "name": r.get("txt"),
                "rate_uah": r.get("rate"),
                "date": r.get("exchangedate"),
            }
            for r in data
        ]
