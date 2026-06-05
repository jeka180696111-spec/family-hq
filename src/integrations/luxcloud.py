"""LuxCloud / LuxPower inverter integration via reverse-engineered HTTP API.

Disclaimer: LuxPower не публикует официальный API.
Поведение основано на снифе их веб-приложения eu.luxpowertek.com.
TP-Link/LuxPower могут изменить API в любой момент — тогда интеграция сломается.

Setup:
  https://eu.luxpowertek.com (или us./asia.) — обычный логин email+пароль.
  Серийник инвертора виден в LuxCloud app: Devices → выбрать инвертор.
"""
from __future__ import annotations

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_REGION_HOSTS = {
    "eu": "https://eu.luxpowertek.com",
    "us": "https://us.luxpowertek.com",
    "asia": "https://asia.luxpowertek.com",
}


class LuxCloudClient:
    """Minimal async client for LuxPowertek web app."""

    def __init__(self, email: str, password: str, region: str, serial: str) -> None:
        self.email = email
        self.password = password
        self.host = _REGION_HOSTS.get(region, _REGION_HOSTS["eu"])
        self.serial = serial
        self._cookies: dict[str, str] = {}

    @classmethod
    def from_settings(cls, settings: Any) -> "LuxCloudClient | None":
        email = getattr(settings, "luxcloud_email", "")
        pwd = getattr(settings, "luxcloud_password", "")
        region = getattr(settings, "luxcloud_region", "eu")
        serial = getattr(settings, "lux_inverter_serial", "")
        if not (email and pwd and serial):
            return None
        return cls(email, pwd, region, serial)

    async def _login(self, session: aiohttp.ClientSession) -> None:
        url = f"{self.host}/WManage/web/login"
        async with session.post(
            url,
            data={"account": self.email, "password": self.password},
            allow_redirects=False,
        ) as resp:
            text = await resp.text()
            if "errCode" in text and "incorrect" in text.lower():
                raise RuntimeError("LuxCloud: неверный логин/пароль")
        # Save session cookies
        self._cookies = {c.key: c.value for c in session.cookie_jar}

    async def _get_json(self, path: str, params: dict | None = None) -> dict:
        async with aiohttp.ClientSession() as session:
            await self._login(session)
            url = f"{self.host}{path}"
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"LuxCloud {path}: HTTP {resp.status}")
                return await resp.json(content_type=None)

    # ─── Public ──────────────────────────────────────────────────────

    async def runtime(self) -> dict:
        """Current state: solar generation, battery %, grid, home consumption."""
        data = await self._get_json(
            "/WManage/api/inverter/getInverterRuntime.json",
            params={"serialNum": self.serial},
        )
        # Common fields seen in responses
        return {
            "pv1_w": data.get("pv1Power") or data.get("ppv1") or 0,
            "pv2_w": data.get("pv2Power") or data.get("ppv2") or 0,
            "pv_total_w": (data.get("pv1Power") or 0) + (data.get("pv2Power") or 0)
                          + (data.get("pv3Power") or 0),
            "battery_pct": data.get("soc", data.get("batCapacity", 0)),
            "battery_charge_w": data.get("pCharge", 0),
            "battery_discharge_w": data.get("pDischarge", 0),
            "grid_import_w": data.get("pToUser", data.get("pGrid", 0)),
            "grid_export_w": data.get("pToGrid", 0),
            "home_consumption_w": data.get("pInv", data.get("pLoad", 0)),
            "status": data.get("status", "unknown"),
            "online": bool(data.get("lostFlag", 1) == 0),
            "raw": data,
        }

    async def today_energy(self) -> dict:
        """Today's totals in kWh."""
        data = await self._get_json(
            "/WManage/api/analyze/runtime/all",
            params={"serialNum": self.serial},
        )
        return {
            "pv_kwh": data.get("ePvDay", 0),
            "battery_charge_kwh": data.get("eChgDay", 0),
            "battery_discharge_kwh": data.get("eDisChgDay", 0),
            "grid_import_kwh": data.get("eToUserDay", 0),
            "grid_export_kwh": data.get("eToGridDay", 0),
            "consumption_kwh": data.get("eUsedDay", 0),
            "raw": data,
        }
