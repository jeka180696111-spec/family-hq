"""Samsung SmartThings integration — robot vacuums (POWERbot), and any
other SmartThings-connected device.

Два способа авторизации:

A) OAuth2 (рекомендуется) — регистрируешь SmartApp на
   developer.smartthings.com, получаешь client_id + client_secret,
   пользователь один раз логинится через /api/tablet/smartthings/login,
   мы храним access_token + refresh_token в OAuthToken, обновляем
   access перед каждым вызовом. Refresh живёт ~30 дней.

B) Personal Access Token (fallback) — устарел, живёт 24 часа. Оставлен
   на случай если OAuth не настроен.
"""
from __future__ import annotations

import time
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_BASE = "https://api.smartthings.com/v1"
_TOKEN_URL = "https://api.smartthings.com/oauth/token"
_AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"


class SmartThingsClient:
    def __init__(
        self,
        token: str = "",
        *,
        memory: Any = None,
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        # PAT для fallback режима
        self.token = token
        # OAuth поля — если заданы, клиент сам управляет access_token из БД
        self._memory = memory
        self._client_id = client_id
        self._client_secret = client_secret

    @classmethod
    def from_settings(cls, settings: Any, memory: Any = None) -> "SmartThingsClient | None":
        cid = getattr(settings, "smartthings_client_id", "")
        csec = getattr(settings, "smartthings_client_secret", "")
        pat = getattr(settings, "smartthings_token", "")
        # OAuth-режим: нужна пара client_id/secret + memory для хранения токенов
        if cid and csec and memory is not None:
            return cls(memory=memory, client_id=cid, client_secret=csec)
        # Fallback на PAT если OAuth не сконфигурен
        if pat:
            return cls(token=pat)
        return None

    async def _get_access_token(self) -> str:
        """OAuth: читаем из БД, при необходимости обновляем через refresh_token."""
        if self.token and not (self._client_id and self._memory):
            return self.token  # PAT-режим
        if self._memory is None:
            raise RuntimeError("SmartThings OAuth: memory not configured")
        # Читаем из БД
        from sqlalchemy import select
        from src.db.models import OAuthToken
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(
                select(OAuthToken).where(OAuthToken.provider == "smartthings")
            )).first()
        if not row:
            raise RuntimeError("SmartThings: пользователь не залогинился. Открой /api/tablet/smartthings/login")
        tok = row[0] if hasattr(row, "_mapping") else row
        # Если не истёк с запасом 60с — используем как есть
        if tok.expires_at and tok.expires_at > int(time.time()) + 60:
            return tok.access_token
        # Обновляем
        return await self._refresh(tok.refresh_token)

    async def _refresh(self, refresh_token: str) -> str:
        """Обновить access_token через refresh_token. Пишем свежие оба в БД."""
        import base64
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _TOKEN_URL, data=data,
                headers={
                    "Authorization": "Basic " + basic,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            ) as r:
                body = await r.text()
                if r.status != 200:
                    raise RuntimeError(f"SmartThings refresh failed HTTP {r.status}: {body[:300]}")
                import json as _json
                payload = _json.loads(body)
        new_access = payload["access_token"]
        new_refresh = payload.get("refresh_token", refresh_token)
        exp_in = int(payload.get("expires_in", 86400))
        # Сохраняем
        from sqlalchemy import update
        from src.db.models import OAuthToken
        from src.utils.time import now_kyiv
        async with self._memory._engine.begin() as conn:
            await conn.execute(
                update(OAuthToken).where(OAuthToken.provider == "smartthings").values(
                    access_token=new_access, refresh_token=new_refresh,
                    expires_at=int(time.time()) + exp_in,
                    updated_at=now_kyiv().isoformat(),
                )
            )
        log.info("smartthings_token_refreshed", expires_in=exp_in)
        return new_access

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        access = await self._get_access_token()
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}
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
        """Pick the first device that looks like a robot vacuum.

        Приоритет матча:
        1) capabilities с robotCleaner* — самый надёжный;
        2) явные ключевые слова в имени (vacuum/powerbot/пылес/robot/гоша);
        3) SmartThings type=ROBOT_CLEANER.
        Тип "OCF" тут НЕ используем — под ним у SmartThings много не-пылесосов
        (лампочки Zigbee-моста, ТВ и т.п.), матчить всё подряд опасно.
        """
        n = (needle or "").strip().lower()
        NAME_HINTS = ("vacuum", "powerbot", "пылес", "пилосос", "roboclean",
                      "robot", "roomba", "гоша", "гоши", "gosha")
        for d in devices:
            caps = d.get("capabilities") or []
            name = (d.get("name") or "").lower()
            is_vacuum = (
                "robotCleanerMovement" in caps
                or "robotCleanerCleaningMode" in caps
                or d.get("type", "") == "ROBOT_CLEANER"
                or any(h in name for h in NAME_HINTS)
            )
            if not is_vacuum:
                continue
            if n and n not in name:
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
