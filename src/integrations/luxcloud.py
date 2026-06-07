"""LuxCloud / LuxPower inverter integration via reverse-engineered HTTP API.

Disclaimer: LuxPower не публикует официальный API.
Поведение основано на снифе их веб-приложения eu.luxpowertek.com.
TP-Link/LuxPower могут изменить API в любой момент — тогда интеграция сломается.

Setup:
  https://eu.luxpowertek.com (или us./asia.) — обычный логин email+пароль.
  Серийник инвертора виден в LuxCloud app: Devices → выбрать инвертор.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()

_REGION_HOSTS = {
    "eu": "https://eu.luxpowertek.com",
    "us": "https://us.luxpowertek.com",
    "asia": "https://asia.luxpowertek.com",
    "inverter": "https://inverter.luxpowertek.com",
    # Newer cloud domains seen in 2025-2026
    "luxcloud_eu": "https://luxcloud.eu",
    "luxcloud_com": "https://www.luxcloud.com",
    "api_luxcloud": "https://api.luxcloud.eu",
}

# Hosts tried in order when initial host fails DNS/connection
_HOST_FALLBACK_ORDER = [
    "https://eu.luxpowertek.com",
    "https://inverter.luxpowertek.com",
    "https://us.luxpowertek.com",
    "https://asia.luxpowertek.com",
    "https://luxcloud.eu",
    "https://api.luxcloud.eu",
    "https://www.luxcloud.com",
]


class LuxCloudClient:
    """Minimal async client for LuxPowertek web app."""

    def __init__(self, email: str, password: str, region: str, serial: str) -> None:
        self.email = email
        self.password = password
        # Default region map, but we'll auto-fail-over if DNS dies
        self.host = _REGION_HOSTS.get(region) or _REGION_HOSTS["eu"]
        self.serial = serial
        self._session: aiohttp.ClientSession | None = None
        self._logged_in = False
        self._host_tried: set[str] = set()

    @classmethod
    def from_settings(cls, settings: Any) -> "LuxCloudClient | None":
        email = getattr(settings, "luxcloud_email", "")
        pwd = getattr(settings, "luxcloud_password", "")
        region = getattr(settings, "luxcloud_region", "eu") or "eu"
        serial = getattr(settings, "lux_inverter_serial", "")
        if not (email and pwd and serial):
            return None
        return cls(email, pwd, region, serial)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) FamilyHQ/1.0",
                    "Accept": "application/json, text/plain, */*",
                },
            )
        return self._session

    async def _login(self) -> None:
        session = await self._ensure_session()
        login_paths = [
            "/WManage/web/login",
            "/WManage/api/login",
            "/login.html",
            "/api/login",  # newer LuxCloud
            "/user/login",
        ]

        # Build host attempt list: current host first, then fallbacks
        hosts_to_try = [self.host] + [h for h in _HOST_FALLBACK_ORDER if h != self.host]

        last_err = None
        for host in hosts_to_try:
            for path in login_paths:
                url = f"{host}{path}"
                try:
                    async with session.post(
                        url,
                        data={"account": self.email, "password": self.password},
                        allow_redirects=False,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        text = await resp.text()
                        if resp.status in (200, 302):
                            if "incorrect" in text.lower() or ("errCode" in text and "0" not in text[:50]):
                                raise RuntimeError("LuxCloud: неверный логин/пароль")
                            # Pin the working host for the lifetime of this client
                            if host != self.host:
                                log.info("luxcloud_host_switched", old=self.host, new=host)
                                self.host = host
                            self._logged_in = True
                            log.info("luxcloud_login_ok", host=host, path=path)
                            return
                        last_err = f"{host}{path} → HTTP {resp.status}: {text[:120]}"
                except aiohttp.ClientError as e:
                    last_err = f"{host}{path} → {type(e).__name__}: {str(e)[:120]}"
                except (aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e:  # type: ignore
                    last_err = f"{host}{path} → timeout/disconnect: {e}"
                except Exception as e:
                    last_err = f"{host}{path} → {type(e).__name__}: {str(e)[:120]}"
        raise RuntimeError(f"LuxCloud login failed on all hosts/paths. Last: {last_err}")

    async def _get_json(self, path: str, params: dict | None = None) -> dict:
        if not self._logged_in:
            await self._login()
        session = await self._ensure_session()
        url = f"{self.host}{path}"
        async with session.get(url, params=params) as resp:
            text = await resp.text()
            if resp.status == 401 or resp.status == 403:
                # Session expired — re-login once
                self._logged_in = False
                await self._login()
                async with session.get(url, params=params) as r2:
                    if r2.status != 200:
                        raise RuntimeError(f"LuxCloud {path}: HTTP {r2.status}")
                    return await r2.json(content_type=None)
            if resp.status != 200:
                raise RuntimeError(f"LuxCloud {path}: HTTP {resp.status} body={text[:300]}")
            try:
                return await resp.json(content_type=None)
            except Exception:
                # Maybe HTML returned (unauthenticated). Try POST as some endpoints expect it
                raise RuntimeError(f"LuxCloud {path}: non-JSON response, first 300 chars: {text[:300]}")

    async def _post_json(self, path: str, body: dict | None = None) -> dict:
        """Some LuxCloud endpoints require POST with form body (e.g. inverter.luxpowertek.com)."""
        if not self._logged_in:
            await self._login()
        session = await self._ensure_session()
        url = f"{self.host}{path}"
        async with session.post(url, data=body or {}) as resp:
            text = await resp.text()
            if resp.status == 401 or resp.status == 403:
                self._logged_in = False
                await self._login()
                async with session.post(url, data=body or {}) as r2:
                    if r2.status != 200:
                        raise RuntimeError(f"LuxCloud {path}: HTTP {r2.status}")
                    return await r2.json(content_type=None)
            if resp.status != 200:
                raise RuntimeError(f"LuxCloud {path}: HTTP {resp.status} body={text[:300]}")
            try:
                return await resp.json(content_type=None)
            except Exception:
                raise RuntimeError(f"LuxCloud {path}: non-JSON response, first 300 chars: {text[:300]}")

    # ─── Public ──────────────────────────────────────────────────────

    async def runtime(self) -> dict:
        """Current state: solar generation, battery %, grid, home consumption.

        Tries known runtime endpoints — different LuxPower platforms expose
        slightly different routes/methods. First success wins.
        """
        endpoints = [
            # (method, path, params/body)
            ("POST", "/WManage/api/inverter/getInverterRuntime", {"serialNum": self.serial}),
            ("GET",  "/WManage/api/inverter/getInverterRuntime.json", {"serialNum": self.serial}),
            ("POST", "/WManage/api/inverter/runtime", {"serialNum": self.serial}),
            ("GET",  "/WManage/api/inverter/runtime", {"serialNum": self.serial}),
        ]
        last_err = None
        data: dict | None = None
        for method, path, payload in endpoints:
            try:
                if method == "GET":
                    data = await self._get_json(path, params=payload)
                else:
                    data = await self._post_json(path, body=payload)
                break
            except Exception as e:
                last_err = f"{method} {path} → {e}"
                continue
        if data is None:
            raise RuntimeError(f"LuxCloud runtime: все эндпоинты упали. Последний: {last_err}")

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
        endpoints = [
            ("POST", "/WManage/api/analyze/runtime/all", {"serialNum": self.serial}),
            ("GET",  "/WManage/api/analyze/runtime/all", {"serialNum": self.serial}),
            ("POST", "/WManage/api/inverter/getInverterEnergyInfo", {"serialNum": self.serial}),
        ]
        last_err = None
        data: dict | None = None
        for method, path, payload in endpoints:
            try:
                if method == "GET":
                    data = await self._get_json(path, params=payload)
                else:
                    data = await self._post_json(path, body=payload)
                break
            except Exception as e:
                last_err = f"{method} {path} → {e}"
                continue
        if data is None:
            raise RuntimeError(f"LuxCloud today_energy: все эндпоинты упали. Последний: {last_err}")

        return {
            "pv_kwh": data.get("ePvDay", 0),
            "battery_charge_kwh": data.get("eChgDay", 0),
            "battery_discharge_kwh": data.get("eDisChgDay", 0),
            "grid_import_kwh": data.get("eToUserDay", 0),
            "grid_export_kwh": data.get("eToGridDay", 0),
            "consumption_kwh": data.get("eUsedDay", 0),
            "raw": data,
        }

    async def recent_events(self, hours: int = 24) -> list[dict]:
        """Try to fetch the inverter event/alarm log from LuxCloud.

        Looks for events like 'Grid Lost', 'Grid Connected', 'Battery Low'
        from the cloud's own notification system. Returns [] if no
        compatible endpoint is found.
        """
        # LuxCloud "Plant Event" — endpoint varies by platform version
        endpoints = [
            ("POST", "/WManage/api/event/list", {"serialNum": self.serial}),
            ("GET",  "/WManage/api/event/list", {"serialNum": self.serial}),
            ("POST", "/WManage/api/inverter/event", {"serialNum": self.serial}),
            ("POST", "/WManage/api/alert/list", {"serialNum": self.serial}),
            ("GET",  "/WManage/web/event/getEventList.json", {"serialNum": self.serial}),
            # Plant Event endpoints (newer LuxCloud)
            ("POST", "/WManage/api/plant/event/list", {"serialNum": self.serial}),
            ("POST", "/WManage/api/plantEvent/list", {"serialNum": self.serial}),
            ("POST", "/WManage/api/plant/getPlantEventList", {"serialNum": self.serial}),
            ("GET",  "/WManage/api/plant/getPlantEventList", {"serialNum": self.serial}),
            ("POST", "/WManage/api/event/plant/list", {"serialNum": self.serial}),
        ]
        data: dict | None = None
        last_err = None
        for method, path, payload in endpoints:
            try:
                if method == "GET":
                    data = await self._get_json(path, params=payload)
                else:
                    data = await self._post_json(path, body=payload)
                break
            except Exception as e:
                last_err = f"{method} {path} → {e}"
                continue
        if data is None:
            log.info("luxcloud_events_unavailable", error=last_err)
            return []

        # Different platforms return events under different keys
        items = (
            data.get("rows")
            or data.get("events")
            or data.get("list")
            or data.get("data")
            or []
        )
        if not isinstance(items, list):
            return []

        # Normalize
        out = []
        for it in items:
            out.append({
                "time": it.get("eventTime") or it.get("time") or it.get("createTime"),
                "code": it.get("eventCode") or it.get("code"),
                "name": it.get("eventName") or it.get("name") or it.get("description"),
                "type": it.get("eventType") or it.get("type"),
                "status": it.get("eventStatus") or it.get("status") or "",  # 'Active'/'Recovered'
                "during_time": it.get("duringTime") or it.get("during_time"),
                "raw": it,
            })
        return out

    async def probe_hosts(self) -> dict:
        """Diagnostic: try logging in to all known hosts, report which respond."""
        results = []
        for host in _HOST_FALLBACK_ORDER:
            entry = {"host": host, "dns": False, "http_ok": False, "login_ok": False, "error": None}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(host, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        entry["dns"] = True
                        entry["http_ok"] = resp.status < 500
                        entry["status"] = resp.status
                # If reachable, try login
                if entry["dns"]:
                    old_host = self.host
                    self.host = host
                    self._logged_in = False
                    self._session = None
                    try:
                        await self._login()
                        entry["login_ok"] = True
                    except Exception as e:
                        entry["error"] = str(e)[:200]
                    finally:
                        self.host = old_host
                        self._logged_in = False
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            results.append(entry)
        return {"checked": len(results), "results": results}

    async def probe_event_endpoints(self) -> dict:
        """Diagnostic: try ALL known endpoint patterns and report raw responses."""
        candidates = [
            # /WManage/web/ paths (alive on eu.luxpowertek.com)
            ("POST", "/WManage/web/event/getEventList"),
            ("GET",  "/WManage/web/event/getEventList"),
            ("POST", "/WManage/web/event/list"),
            ("POST", "/WManage/web/event/getList"),
            ("POST", "/WManage/web/event/getEventList.json"),
            ("POST", "/WManage/web/inverter/event"),
            ("POST", "/WManage/web/inverter/getEventList"),
            ("POST", "/WManage/web/monitor/event"),
            ("POST", "/WManage/web/monitor/getEventList"),
            ("POST", "/WManage/web/monitor/inverter/event"),
            ("POST", "/WManage/web/alarm/list"),
            ("POST", "/WManage/web/alarm/getAlarmList"),
            ("POST", "/WManage/web/plant/event/list"),
            ("POST", "/WManage/web/plant/getEventList"),
            # /WManage/api/ paths
            ("POST", "/WManage/api/event/list"),
            ("GET",  "/WManage/api/event/list"),
            ("POST", "/WManage/api/plant/event/list"),
            ("POST", "/WManage/api/plantEvent/list"),
            ("POST", "/WManage/api/plant/getPlantEventList"),
            ("POST", "/WManage/api/event/plant/list"),
            ("POST", "/WManage/api/inverter/event"),
            ("POST", "/WManage/api/inverter/getEventList"),
            ("POST", "/WManage/api/alert/list"),
            ("POST", "/WManage/api/v1/event/list"),
            ("POST", "/WManage/api/v2/event/list"),
        ]
        results = []
        for method, path in candidates:
            url = f"{self.host}{path}"
            try:
                if method == "GET":
                    data = await self._get_json(path, params={"serialNum": self.serial})
                else:
                    data = await self._post_json(path, body={"serialNum": self.serial})
                # Look for event-like rows
                rows = (data.get("rows") or data.get("events") or data.get("list")
                        or data.get("data") or data.get("result") or [])
                sample = None
                if isinstance(rows, list) and rows:
                    sample = rows[0]
                elif isinstance(rows, dict):
                    sample = rows
                results.append({
                    "method": method,
                    "path": path,
                    "status": "ok",
                    "row_count": len(rows) if isinstance(rows, list) else "?",
                    "top_keys": list(data.keys())[:10],
                    "sample": str(sample)[:400] if sample else None,
                })
            except Exception as e:
                results.append({
                    "method": method,
                    "path": path,
                    "status": "error",
                    "error": str(e)[:200],
                })
        return {
            "host": self.host,
            "serial": self.serial,
            "tried": len(results),
            "results": results,
        }

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
