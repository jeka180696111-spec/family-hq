"""Tuya / Smart Life integration via Tuya Cloud OpenAPI.

Requires env:
  TUYA_ACCESS_ID, TUYA_ACCESS_SECRET, TUYA_REGION (eu/us/cn/in), TUYA_APP_USER_UID

Setup (one-time):
  1. https://iot.tuya.com → create developer account (free)
  2. Cloud → Project → Create (Smart Home / Custom Development)
  3. Subscribe to: IoT Core, Smart Home Basic Service
  4. Linked Devices → Link App Account → scan QR from Smart Life app
  5. Get UID from linked account, Access ID/Secret from project
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_REGION_HOSTS = {
    "eu": "https://openapi.tuyaeu.com",
    "us": "https://openapi.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}


class TuyaClient:
    """Minimal async client for Tuya Cloud OpenAPI v1.0."""

    def __init__(self, access_id: str, access_secret: str, region: str, app_user_uid: str) -> None:
        self.access_id = access_id
        self.access_secret = access_secret
        self.host = _REGION_HOSTS.get(region, _REGION_HOSTS["eu"])
        self.uid = app_user_uid
        self._token: str | None = None
        self._token_exp = 0.0

    @classmethod
    def from_settings(cls, settings: Any) -> "TuyaClient | None":
        aid = getattr(settings, "tuya_access_id", None)
        secret = getattr(settings, "tuya_access_secret", None)
        uid = getattr(settings, "tuya_app_user_uid", None)
        region = getattr(settings, "tuya_region", "eu")
        if not (aid and secret and uid):
            return None
        return cls(aid, secret, region, uid)

    # ─── Auth ────────────────────────────────────────────────────────

    async def _ensure_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token

        path = "/v1.0/token?grant_type=1"
        ts = str(int(now * 1000))
        sign = self._sign("GET", path, "", ts, "")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.host + path,
                headers={
                    "client_id": self.access_id,
                    "sign": sign,
                    "t": ts,
                    "sign_method": "HMAC-SHA256",
                },
            ) as resp:
                data = await resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Tuya auth failed: {data}")
        result = data["result"]
        self._token = result["access_token"]
        self._token_exp = now + int(result.get("expire_time", 7200))
        return self._token

    def _sign(self, method: str, path: str, body: str, ts: str, token: str) -> str:
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        string_to_sign = f"{method}\n{body_hash}\n\n{path}"
        signing_input = self.access_id + token + ts + string_to_sign
        return hmac.new(self.access_secret.encode(), signing_input.encode(), hashlib.sha256).hexdigest().upper()

    async def _request(self, method: str, path: str, body: str = "") -> dict:
        token = await self._ensure_token()
        ts = str(int(time.time() * 1000))
        sign = self._sign(method, path, body, ts, token)
        headers = {
            "client_id": self.access_id,
            "access_token": token,
            "sign": sign,
            "t": ts,
            "sign_method": "HMAC-SHA256",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            kwargs: dict = {"headers": headers}
            if body:
                kwargs["data"] = body
            async with session.request(method, self.host + path, **kwargs) as resp:
                data = await resp.json()
        return data

    # ─── Public API ──────────────────────────────────────────────────

    async def list_devices(self) -> list[dict]:
        """Get devices linked to the user's Smart Life account."""
        data = await self._request("GET", f"/v1.0/users/{self.uid}/devices")
        if not data.get("success"):
            raise RuntimeError(f"Tuya list_devices failed: {data}")
        devices = data.get("result", []) or []
        # Pick the useful fields
        return [
            {
                "id": d["id"],
                "name": d.get("name", ""),
                "category": d.get("category", ""),
                "product_name": d.get("product_name", ""),
                "online": d.get("online", False),
                "status": d.get("status", []),
            }
            for d in devices
        ]

    async def control(self, device: str, action: str) -> dict:
        """Toggle a switch device. action ∈ on/off/toggle/status."""
        devices = await self.list_devices()
        target = self._find_device(devices, device)
        if not target:
            return {"error": f"Не нашёл устройство по имени/ID '{device}'", "available": [d["name"] for d in devices]}

        if action == "status":
            return {"device": target["name"], "online": target["online"], "status": target["status"]}

        # Find a switch-like code
        switch_code = None
        for s in target["status"]:
            code = s.get("code", "")
            if code == "switch" or code.startswith("switch_"):
                switch_code = code
                break
        if not switch_code:
            return {"error": f"У '{target['name']}' нет переключателя (switch). Список dpts: {target['status']}"}

        current = next((s["value"] for s in target["status"] if s["code"] == switch_code), False)
        desired = {"on": True, "off": False, "toggle": not current}.get(action, current)

        import json
        body = json.dumps({"commands": [{"code": switch_code, "value": desired}]})
        data = await self._request("POST", f"/v1.0/devices/{target['id']}/commands", body=body)
        return {
            "device": target["name"],
            "action": action,
            "set_to": desired,
            "success": data.get("success", False),
            "raw": data.get("msg", ""),
        }

    async def read_sensor(self, sensor: str) -> dict:
        devices = await self.list_devices()
        if not sensor:
            # Return any sensor-like device
            sensors = [d for d in devices if "sensor" in d.get("category", "") or "temp" in d.get("name", "").lower()]
            return {"count": len(sensors), "sensors": sensors}
        target = self._find_device(devices, sensor)
        if not target:
            return {"error": f"Не нашёл датчик '{sensor}'", "available": [d["name"] for d in devices]}
        # Reformat status into readable
        readings = {}
        temp_str = None
        humi_str = None
        batt_str = None
        for s in target["status"]:
            code = s.get("code", "")
            val = s.get("value")
            if "temp" in code:
                temp_val = val / 10 if isinstance(val, (int, float)) and val > 100 else val
                readings["temperature"] = f"{temp_val}°C"
                temp_str = f"{temp_val}°C"
            elif "humi" in code:
                readings["humidity"] = f"{val}%"
                humi_str = f"{val}%"
            elif "battery" in code:
                readings["battery"] = f"{val}%"
                batt_str = f"{val}%"
            else:
                readings[code] = val

        # Pre-formatted display string with emoji — agents pass through as-is
        parts = []
        if temp_str:
            parts.append(f"🌡 {temp_str}")
        if humi_str:
            parts.append(f"💧 {humi_str}")
        if batt_str:
            parts.append(f"🔋 {batt_str}")
        formatted = " | ".join(parts) if parts else "нет данных"

        return {
            "device": target["name"],
            "online": target["online"],
            "readings": readings,
            "formatted": f"📍 {target['name']}: {formatted}",
            "display_instruction": (
                "Покажи юзеру значение из поля 'formatted' без изменений. "
                "Не переформулируй и не добавляй своих комментариев если не просят."
            ),
        }

    @staticmethod
    def _find_device(devices: list[dict], needle: str) -> dict | None:
        n = needle.strip().lower()
        for d in devices:
            if d["id"] == needle:
                return d
            if n in d.get("name", "").lower():
                return d
        return None
