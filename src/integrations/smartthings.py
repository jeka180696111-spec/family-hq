"""Samsung SmartThings integration — robot vacuums (POWERbot), and any
other SmartThings-connected device.

Setup:
  1. https://account.smartthings.com/tokens — create Personal Access Token
  2. Grant scopes: 'r:devices:*' and 'x:devices:*' (read + control)
  3. Add SMARTTHINGS_TOKEN to Railway env

If your POWERbot-E doesn't show up in SmartThings:
  - Open the SmartThings app on phone
  - Add device → Samsung → Vacuums → follow pairing
  - Once it's there, this integration sees it.
"""
from __future__ import annotations

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_BASE = "https://api.smartthings.com/v1"


class SmartThingsClient:
    def __init__(self, token: str) -> None:
        self.token = token

    @classmethod
    def from_settings(cls, settings: Any) -> "SmartThingsClient | None":
        tok = getattr(settings, "smartthings_token", "")
        if not tok:
            return None
        return cls(tok)

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            kwargs: dict = {"headers": headers}
            if json_body is not None:
                kwargs["json"] = json_body
            async with session.request(method, f"{_BASE}{path}", **kwargs) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"SmartThings {method} {path}: HTTP {resp.status}: {text[:300]}")
                if not text:
                    return {}
                import json as _json
                return _json.loads(text)

    # ─── Devices ────────────────────────────────────────────────────

    async def list_devices(self) -> list[dict]:
        data = await self._request("GET", "/devices")
        items = data.get("items", []) or []
        return [
            {
                "id": d.get("deviceId"),
                "name": d.get("label") or d.get("name"),
                "type": d.get("type"),
                "capabilities": [
                    c.get("id") for comp in d.get("components", [])
                    for c in (comp.get("capabilities") or [])
                ],
                "room_name": d.get("roomName"),
            }
            for d in items
        ]

    async def get_status(self, device_id: str) -> dict:
        data = await self._request("GET", f"/devices/{device_id}/status")
        return data

    async def send_command(self, device_id: str, capability: str, command: str, arguments: list | None = None) -> dict:
        body = {
            "commands": [
                {
                    "component": "main",
                    "capability": capability,
                    "command": command,
                    "arguments": arguments or [],
                }
            ]
        }
        return await self._request("POST", f"/devices/{device_id}/commands", json_body=body)

    # ─── Vacuum helpers ─────────────────────────────────────────────

    def find_vacuum(self, devices: list[dict], needle: str = "") -> dict | None:
        """Pick the first device that looks like a robot vacuum."""
        n = (needle or "").strip().lower()
        for d in devices:
            caps = d.get("capabilities") or []
            is_vacuum = (
                "robotCleanerMovement" in caps
                or "robotCleanerCleaningMode" in caps
                or d.get("type", "") in ("OCF", "ROBOT_CLEANER")
                or "vacuum" in (d.get("name") or "").lower()
                or "powerbot" in (d.get("name") or "").lower()
                or "пылес" in (d.get("name") or "").lower()
                or "пилосос" in (d.get("name") or "").lower()
            )
            if not is_vacuum:
                continue
            if n and n not in (d.get("name") or "").lower():
                continue
            return d
        return None

    async def vacuum_summary(self, device: dict) -> dict:
        status = await self.get_status(device["id"])
        main = (status.get("components", {}).get("main", {}) or {})

        def pick(cap: str, attr: str):
            return main.get(cap, {}).get(attr, {}).get("value")

        return {
            "device": device["name"],
            "id": device["id"],
            "battery": pick("battery", "battery"),
            "movement": pick("robotCleanerMovement", "robotCleanerMovement"),
            "mode": pick("robotCleanerCleaningMode", "robotCleanerCleaningMode"),
            "turbo": pick("robotCleanerTurboMode", "robotCleanerTurboMode"),
            "power": pick("switch", "switch"),
        }

    async def vacuum_start(self, device_id: str, mode: str = "auto") -> dict:
        # mode ∈ auto / part / repeat / manual / map
        return await self.send_command(
            device_id, "robotCleanerCleaningMode", "setRobotCleanerCleaningMode", [mode]
        )

    async def vacuum_stop(self, device_id: str) -> dict:
        return await self.send_command(
            device_id, "robotCleanerMovement", "setRobotCleanerMovement", ["homing"]
        )

    async def vacuum_pause(self, device_id: str) -> dict:
        return await self.send_command(
            device_id, "robotCleanerMovement", "setRobotCleanerMovement", ["idle"]
        )
