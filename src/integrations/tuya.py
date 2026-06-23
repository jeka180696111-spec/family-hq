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
        self._home_id: str | None = None
        # Lazy-created shared aiohttp session so every command reuses
        # the same TCP/TLS connection instead of leaking sockets per call.
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

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
        session = await self._get_session()
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
        session = await self._get_session()
        kwargs: dict = {"headers": headers}
        if body:
            kwargs["data"] = body
        async with session.request(method, self.host + path, **kwargs) as resp:
            data = await resp.json()
        return data

    # ─── Public API ──────────────────────────────────────────────────

    async def list_devices(self) -> list[dict]:
        """Get devices linked to the user's Smart Life account.

        Retries once on transient failure — Tuya Cloud sporadically returns
        non-success responses (~2-5%), which used to leak as 'датчики не
        отвечают' even though next call worked.
        """
        import asyncio
        data = await self._request("GET", f"/v1.0/users/{self.uid}/devices")
        if not data.get("success"):
            log.warning("tuya_list_devices_retry", first=str(data)[:200])
            await asyncio.sleep(1.0)
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

    # Strong markers for «this is an IR hub». Bare «ик» (2 chars) used to
    # be here but matches «Датчик», «Телик», «Алкоголик», … — replaced
    # with «ик-», «ик пульт», «ик-пульт» and similar word-bounded forms.
    _IR_HUB_PRODUCT_HINTS = (
        "infrared", "ir hub", "ir blaster", "ir control",
        "пульт", "remote control",
        "ик-", "ик пульт", "ик-хаб", "ик хаб",
    )

    @classmethod
    def _is_ir_hub(cls, dev: dict) -> bool:
        if dev.get("category") in ("wnykq", "infrared"):
            return True
        name = (dev.get("name", "") + " " + dev.get("product_name", "")).lower()
        return any(h in name for h in cls._IR_HUB_PRODUCT_HINTS)

    @classmethod
    def _find_ir_hub(cls, devices: list[dict]) -> dict | None:
        for d in devices:
            if cls._is_ir_hub(d):
                return d
        return None

    @classmethod
    def _is_ir_ac(cls, dev: dict) -> bool:
        """Virtual AC under an IR hub — no switch DP, name contains AC token."""
        if any(s.get("code", "") in ("switch",) or s.get("code", "").startswith("switch_")
               for s in dev.get("status", [])):
            return False
        name = (dev.get("name", "") + " " + dev.get("product_name", "")).lower()
        for syn in cls._SYNONYM_GROUPS:
            if "кондер" in syn and any(token in name for token in syn):
                return True
        return False

    async def _wake_device(self, device_id: str) -> None:
        """Poke a sleeping device by reading its status. Most cheap Tuya
        IR hubs come back online within ~3-5 seconds of the first status
        request after sleeping."""
        try:
            await self._request("GET", f"/v1.0/devices/{device_id}/status")
        except Exception:
            pass

    async def _ir_ac_command(self, hub_id: str, ac_id: str, payload: dict) -> dict:
        """POST to /v2.0/infrareds/{hub}/air-conditioners/{ac}/command.

        Retries once if the hub appears offline — sends a status read to
        wake it, sleeps 3s, retries the command. Most Tuya IR hubs sleep
        after a few minutes of idleness and need a poke to come back."""
        import asyncio
        import json
        body = json.dumps(payload)
        path = f"/v2.0/infrareds/{hub_id}/air-conditioners/{ac_id}/command"

        data = await self._request("POST", path, body=body)
        if data.get("success"):
            return data

        # Failed — likely the IR hub is asleep. Wake & retry.
        # Tuya cloud doesn't always return a clean "offline" string when
        # the hub momentarily can't reach the AC — sometimes it's a generic
        # "command failed" or empty msg. Only skip retry on clearly
        # non-recoverable errors (auth/permission/argument).
        msg = str(data.get("msg") or data.get("code") or "").lower()
        non_recoverable = (
            "permission" in msg or "forbidden" in msg or "unauthor" in msg
            or "token" in msg or "invalid param" in msg or "param error" in msg
            or "no permission" in msg
        )
        if non_recoverable:
            return data

        log.info("tuya_ir_hub_wake_retry", hub=hub_id, first_msg=msg[:120])
        await self._wake_device(hub_id)
        await asyncio.sleep(3.0)
        data2 = await self._request("POST", path, body=body)
        # Surface both attempts so the caller can show useful diagnostics
        if not data2.get("success"):
            data2.setdefault("first_attempt", data.get("msg") or data.get("code"))
        else:
            data2["wake_retried"] = True
        return data2

    async def control(self, device: str, action: str) -> dict:
        """Toggle a device. action ∈ on/off/toggle/status.

        Path A: regular switch DP (smart plugs, lights, switches).
        Path B: IR-virtual AC under an IR hub — uses /v2.0/infrareds/.../command.
        """
        devices = await self.list_devices()
        target = self._find_device(devices, device)
        if not target:
            return {"error": f"Не нашёл устройство по имени/ID '{device}'", "available": [d["name"] for d in devices]}

        if action == "status":
            return {"device": target["name"], "online": target["online"], "status": target["status"]}

        # Path A — regular switch DP
        switch_code = None
        for s in target["status"]:
            code = s.get("code", "")
            if code == "switch" or code.startswith("switch_"):
                switch_code = code
                break

        if switch_code:
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

        # Path B — IR-virtual AC (no switch DP)
        if self._is_ir_ac(target):
            hub = self._find_ir_hub(devices)
            if not hub:
                return {"error": f"У '{target['name']}' нет switch и IR-хаб не найден"}
            power = 1 if action in ("on", "toggle") else 0  # toggle treated as on
            # Default sensible cool@24 — user can override with set_temperature/set_mode after.
            payload = {"power": power, "mode": 0, "temp": 24, "wind": 0}
            data = await self._ir_ac_command(hub["id"], target["id"], payload)
            return {
                "device": target["name"],
                "via_ir_hub": hub["name"],
                "action": action,
                "payload": payload,
                "success": data.get("success", False),
                "raw": data.get("msg", ""),
            }

        return {"error": f"У '{target['name']}' нет переключателя (switch). Список dpts: {target['status']}"}

    # Mode aliases — what user types → Tuya DP value (lower-case)
    _MODE_ALIASES = {
        "cool": "cold",        # охлаждение → cold (часто), reuse below
        "cold": "cold",
        "холод": "cold",
        "охлаждение": "cold",
        "охлад": "cold",
        "heat": "hot",
        "hot": "hot",
        "тепло": "hot",
        "обогрев": "hot",
        "теплый": "hot",
        "тёплый": "hot",
        "dry": "wet",
        "wet": "wet",
        "осушение": "wet",
        "сушка": "wet",
        "fan": "wind",
        "wind": "wind",
        "вентилятор": "wind",
        "вентиляция": "wind",
        "auto": "auto",
        "авто": "auto",
        "автоматический": "auto",
    }

    # IR AC mode value mapping: Tuya expects ints, not strings.
    _IR_MODE_INT = {"cold": 0, "hot": 1, "auto": 2, "wind": 3, "wet": 4}

    # Fan-speed aliases: ru/en → Tuya `wind` int (0=auto, 1=low, 2=med, 3=high)
    _FAN_SPEED_ALIASES = {
        "auto": 0, "авто": 0, "автоматический": 0,
        "low": 1, "low_speed": 1, "min": 1, "minimal": 1,
        "тихо": 1, "тихий": 1, "минимум": 1, "минимальная": 1,
        "слабая": 1, "слабый": 1, "ниже": 1, "низкая": 1, "низкий": 1,
        "sleep": 1, "night": 1,
        "med": 2, "medium": 2, "mid": 2, "normal": 2,
        "средняя": 2, "средний": 2, "норм": 2, "нормальная": 2,
        "high": 3, "max": 3, "maximum": 3, "turbo": 3, "boost": 3,
        "высокая": 3, "высокий": 3, "максимум": 3, "максимальная": 3,
        "макс": 3, "турбо": 3,
    }

    async def set_fan_speed(
        self, device: str, speed: str | int,
        mode: str | None = None, temperature: int | None = None,
    ) -> dict:
        """Set fan speed on an AC. Accepts ru/en aliases or 0-3 int.
        For IR ACs the IR payload bundles power+mode+temp+wind, so we
        also accept optional current mode/temperature to keep them stable."""
        devices = await self.list_devices()
        target = self._find_device(devices, device)
        if not target:
            return {
                "error": f"Не нашёл устройство '{device}'",
                "available": [d["name"] for d in devices],
            }
        # Normalise speed
        if isinstance(speed, int):
            wind = max(0, min(3, speed))
        else:
            s_norm = (speed or "").strip().lower()
            wind = self._FAN_SPEED_ALIASES.get(s_norm)
            if wind is None:
                return {
                    "error": f"скорость {speed!r} не распознана",
                    "valid_speeds": sorted({"auto", "low", "med", "high",
                                            "тихо", "средняя", "высокая",
                                            "макс", "турбо", "sleep"}),
                }

        # IR AC path
        if self._is_ir_ac(target):
            hub = self._find_ir_hub(devices)
            if not hub:
                return {"error": "IR-хаб не найден"}
            # Keep mode/temp stable unless caller passed new ones
            ir_mode = self._IR_MODE_INT.get(
                self._MODE_ALIASES.get((mode or "").strip().lower(), "cold"), 0,
            ) if mode else 0
            try:
                t = max(16, min(30, int(temperature))) if temperature else 24
            except (TypeError, ValueError):
                t = 24
            payload = {"power": 1, "mode": ir_mode, "temp": t, "wind": wind}
            data = await self._ir_ac_command(hub["id"], target["id"], payload)
            return {
                "device": target["name"],
                "via_ir_hub": hub["name"],
                "action": "set_fan_speed",
                "set_to": wind,
                "speed_label": ["auto", "low", "med", "high"][wind],
                "payload": payload,
                "success": data.get("success", False),
                "raw": data.get("msg", ""),
            }

        # Direct DP path for non-IR ACs (rare for our setup)
        codes = [s.get("code", "") for s in target.get("status", [])]
        fan_code = next(
            (c for c in codes if c in ("wind_speed", "fan_speed", "windspeed", "wind")),
            None,
        ) or "wind"
        import json
        body = json.dumps({"commands": [{"code": fan_code, "value": wind}]})
        data = await self._request("POST", f"/v1.0/devices/{target['id']}/commands", body=body)
        return {
            "device": target["name"],
            "action": "set_fan_speed",
            "set_to": wind,
            "speed_label": ["auto", "low", "med", "high"][wind],
            "code": fan_code,
            "success": data.get("success", False),
            "raw": data.get("msg", ""),
        }

    async def set_temperature(self, device: str, temperature: int) -> dict:
        """Set target temperature on an AC/IR-AC device. Accepts 16-30 °C."""
        devices = await self.list_devices()
        target = self._find_device(devices, device)
        if not target:
            return {
                "error": f"Не нашёл устройство '{device}'",
                "available": [d["name"] for d in devices],
            }
        try:
            t = int(temperature)
        except (TypeError, ValueError):
            return {"error": f"температура должна быть числом, получено {temperature!r}"}
        if not (16 <= t <= 30):
            return {"error": f"температура {t}°C вне диапазона 16-30°C"}

        # IR AC path
        if self._is_ir_ac(target):
            hub = self._find_ir_hub(devices)
            if not hub:
                return {"error": "IR-хаб не найден"}
            payload = {"power": 1, "mode": 0, "temp": t, "wind": 0}
            data = await self._ir_ac_command(hub["id"], target["id"], payload)
            return {
                "device": target["name"],
                "via_ir_hub": hub["name"],
                "action": "set_temperature",
                "set_to": t,
                "payload": payload,
                "success": data.get("success", False),
                "raw": data.get("msg", ""),
            }

        # Direct DP path for non-IR ACs
        codes = [s.get("code", "") for s in target.get("status", [])]
        temp_code = next(
            (c for c in codes if c in ("temp_set", "temperature", "settemp", "temp")),
            None,
        ) or "temp"
        import json
        body = json.dumps({"commands": [{"code": temp_code, "value": t}]})
        data = await self._request("POST", f"/v1.0/devices/{target['id']}/commands", body=body)
        return {
            "device": target["name"],
            "action": "set_temperature",
            "set_to": t,
            "code": temp_code,
            "success": data.get("success", False),
            "raw": data.get("msg", ""),
        }

    async def set_mode(self, device: str, mode: str, temperature: int = 24) -> dict:
        """Set AC mode. Accepts ru/en aliases — see _MODE_ALIASES.
        For IR ACs the command bundles mode+temp, so we also accept a temp."""
        devices = await self.list_devices()
        target = self._find_device(devices, device)
        if not target:
            return {
                "error": f"Не нашёл устройство '{device}'",
                "available": [d["name"] for d in devices],
            }
        m_norm = (mode or "").strip().lower()
        tuya_mode = self._MODE_ALIASES.get(m_norm)
        if not tuya_mode:
            return {
                "error": f"режим {mode!r} не распознан",
                "valid_modes": sorted(set(self._MODE_ALIASES.values())),
            }

        # IR AC path
        if self._is_ir_ac(target):
            hub = self._find_ir_hub(devices)
            if not hub:
                return {"error": "IR-хаб не найден"}
            try:
                t = max(16, min(30, int(temperature)))
            except (TypeError, ValueError):
                t = 24
            payload = {"power": 1, "mode": self._IR_MODE_INT.get(tuya_mode, 0), "temp": t, "wind": 0}
            data = await self._ir_ac_command(hub["id"], target["id"], payload)
            return {
                "device": target["name"],
                "via_ir_hub": hub["name"],
                "action": "set_mode",
                "set_to": tuya_mode,
                "temperature": t,
                "payload": payload,
                "success": data.get("success", False),
                "raw": data.get("msg", ""),
            }

        # Direct DP path
        codes = [s.get("code", "") for s in target.get("status", [])]
        mode_code = next(
            (c for c in codes if c in ("mode", "ac_mode", "work_mode")),
            None,
        ) or "mode"
        import json
        body = json.dumps({"commands": [{"code": mode_code, "value": tuya_mode}]})
        data = await self._request("POST", f"/v1.0/devices/{target['id']}/commands", body=body)
        return {
            "device": target["name"],
            "action": "set_mode",
            "set_to": tuya_mode,
            "code": mode_code,
            "success": data.get("success", False),
            "raw": data.get("msg", ""),
        }

    # ─── Tap-to-Run scenes (Tuya Smart Life «Миттєвий сценарій») ──────
    #
    # Why scenes: direct IR-AC commands via /v2.0/infrareds/.../command
    # are unreliable through Tuya cloud (hub frequently «не отвечает»),
    # but Tap-to-Run scenes — same hub, same cloud — fire reliably from
    # the app. So we route AC control through pre-created scenes.

    async def _ensure_home_id(self) -> str | None:
        if self._home_id:
            return self._home_id
        try:
            data = await self._request("GET", f"/v1.0/users/{self.uid}/homes")
            homes = data.get("result", []) or []
            if homes:
                self._home_id = str(homes[0].get("home_id") or homes[0].get("id") or "")
                return self._home_id or None
        except Exception:
            log.exception("tuya_homes_lookup_failed")
        return None

    async def list_scenes(self) -> list[dict]:
        """Return Tap-to-Run scenes for the user's primary home.
        Tries v2.0 first (currently the only one with stable access on
        Smart Home Basic), falls back to v1.0 if v2 returns nothing."""
        home_id = await self._ensure_home_id()
        if not home_id:
            log.warning("tuya_list_scenes_no_home")
            return []

        items: list[dict] = []

        # v2.0 endpoint — Smart Home Scene Linkage (preferred).
        # Pull both type=scene (tap-to-run) and type=automation, paginated.
        for scene_type in ("scene", "automation"):
            has_more = True
            last_id = ""
            while has_more:
                path = (
                    f"/v2.0/cloud/scene/rule"
                    f"?space_id={home_id}&type={scene_type}&size=50"
                )
                if last_id:
                    path += f"&last_id={last_id}"
                data2 = await self._request("GET", path)
                if not data2.get("success"):
                    log.warning(
                        "tuya_list_scenes_v2_failed",
                        scene_type=scene_type,
                        msg=str(data2.get("msg"))[:200], code=data2.get("code"),
                    )
                    break
                res = data2.get("result") or {}
                if isinstance(res, dict):
                    batch = res.get("list", []) or []
                    has_more = bool(res.get("has_more"))
                    if batch:
                        last_id = str(batch[-1].get("id") or "")
                else:
                    batch = res or []
                    has_more = False
                items.extend(batch)
                if not batch:
                    break

        # v1.0 endpoint — fallback only if v2 was empty.
        if not items:
            data = await self._request("GET", f"/v1.0/homes/{home_id}/scenes")
            if data.get("success"):
                items = data.get("result", []) or []
            else:
                log.warning(
                    "tuya_list_scenes_v1_failed",
                    msg=str(data.get("msg"))[:200], code=data.get("code"),
                )

        # Dedup by id (v2 may overlap scene/automation tabs)
        seen: set[str] = set()
        out: list[dict] = []
        for s in items:
            sid = str(s.get("id") or s.get("scene_id") or s.get("rule_id") or "")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append({
                "id": sid,
                "name": s.get("name", ""),
                "status": s.get("status", ""),
            })
        return out

    async def diagnose_scenes(self) -> dict:
        """Return raw API responses so we can see WHY the scenes list is empty."""
        out: dict = {}
        try:
            homes = await self._request("GET", f"/v1.0/users/{self.uid}/homes")
            out["homes_raw"] = {
                "success": homes.get("success"),
                "code": homes.get("code"),
                "msg": str(homes.get("msg"))[:200],
                "result_count": len(homes.get("result", []) or []),
                "result_sample": (homes.get("result") or [])[:2],
            }
        except Exception as e:
            out["homes_error"] = f"{type(e).__name__}: {e}"
            return out

        home_id = await self._ensure_home_id()
        out["home_id"] = home_id
        if not home_id:
            return out

        try:
            v1 = await self._request("GET", f"/v1.0/homes/{home_id}/scenes")
            out["scenes_v1"] = {
                "success": v1.get("success"),
                "code": v1.get("code"),
                "msg": str(v1.get("msg"))[:200],
                "result_count": len(v1.get("result", []) or []),
                "result_sample": (v1.get("result") or [])[:3],
            }
        except Exception as e:
            out["scenes_v1_error"] = f"{type(e).__name__}: {e}"

        try:
            v2 = await self._request(
                "GET", f"/v2.0/cloud/scene/rule?space_id={home_id}&type=scene",
            )
            out["scenes_v2"] = {
                "success": v2.get("success"),
                "code": v2.get("code"),
                "msg": str(v2.get("msg"))[:200],
                "result_sample": str(v2.get("result"))[:400],
            }
        except Exception as e:
            out["scenes_v2_error"] = f"{type(e).__name__}: {e}"

        return out

    @staticmethod
    def _score_scene_match(query: str, scene_name: str) -> int:
        """Rough scoring: token overlap + digit (temperature) match weights
        heaviest. Higher = better match."""
        import re
        q = query.lower()
        s = scene_name.lower()
        q_digits = set(re.findall(r"\d+", q))
        s_digits = set(re.findall(r"\d+", s))
        score = 0
        # Temperature match dominates — if юзер сказал 25 и сцена имеет 25, это почти гарантия
        if q_digits and s_digits and (q_digits & s_digits):
            score += 100
        # Off/on intent
        off_words = ("выкл", "вируб", "off", "відключ", "віключ", "вырубай")
        on_words = ("вкл", "увімкн", "увімк", "on", "включи", "включай")
        if any(w in q for w in off_words) and any(w in s for w in off_words):
            score += 80
        if any(w in q for w in on_words) and any(w in s for w in on_words):
            score += 60
        # Cold/heat intent
        if any(w in q for w in ("холод", "cold", "охлад", "прохлад")) and \
           any(w in s for w in ("холод", "cold")):
            score += 20
        if any(w in q for w in ("тепл", "heat", "обогрев", "грей")) and \
           any(w in s for w in ("тепл", "heat")):
            score += 20
        # Generic token overlap (each shared 3+-letter token)
        for tok in re.findall(r"[а-яёa-z]{3,}", q):
            if tok in s:
                score += 5
        return score

    async def find_scene(self, query: str) -> dict | None:
        """Best-match scene by name. Returns None if no plausible match."""
        scenes = await self.list_scenes()
        if not scenes:
            return None
        ranked = sorted(
            ((self._score_scene_match(query, s["name"]), s) for s in scenes),
            key=lambda x: x[0], reverse=True,
        )
        top_score, top = ranked[0]
        # Need at least one signal (digit, on/off, or token overlap)
        if top_score < 20:
            return None
        # If second-best ties within 5 points AND non-trivial — ambiguous
        if len(ranked) > 1 and ranked[1][0] >= top_score - 5 and ranked[1][0] >= 80:
            return {"ambiguous": True, "candidates": [s for _, s in ranked[:4] if _ >= top_score - 20]}
        return top

    async def run_scene(self, scene_id: str) -> dict:
        """Trigger a Tap-to-Run scene by id."""
        home_id = await self._ensure_home_id()
        if not home_id:
            return {"error": "Не нашёл home_id в Tuya"}
        data = await self._request(
            "POST", f"/v1.0/homes/{home_id}/scenes/{scene_id}/trigger",
        )
        return {
            "scene_id": scene_id,
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

    # Synonym groups — any token in a group matches any device whose name
    # contains ANY other token in the same group. So «телевизор» matches
    # «Розетка ТВ», «свет» matches «light strip», etc.
    _SYNONYM_GROUPS = (
        ("телевизор", "телек", "тв", "tv", "телик"),
        ("кондер", "кондиционер", "ac", "сплит", "сплит-система"),
        ("бойлер", "boiler", "водонагреватель", "котёл", "котел"),
        ("свет", "светильник", "лампа", "люстра", "light", "лампочка"),
        ("розетка", "plug", "socket"),
        ("чайник", "kettle"),
        ("стиралка", "стиральная машина", "washer"),
        ("посудомойка", "dishwasher"),
        ("кофеварка", "coffee"),
        ("увлажнитель", "humidifier"),
        ("пылесос", "робот", "vacuum"),
        ("кроватка", "детская", "малыш"),
    )

    @classmethod
    def _find_device(cls, devices: list[dict], needle: str) -> dict | None:
        n = (needle or "").strip().lower()
        if not n:
            return None
        for d in devices:
            if d["id"] == needle:
                return d
            if n in d.get("name", "").lower():
                return d
        # Try synonyms — expand the needle into every alias and look for
        # device names containing any of them.
        expanded: set[str] = set()
        for group in cls._SYNONYM_GROUPS:
            if n in group:
                expanded.update(group)
        for syn in expanded:
            if syn == n:
                continue
            for d in devices:
                if syn in d.get("name", "").lower():
                    return d
        return None
