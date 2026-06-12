"""Киевстар personal-account client — reverse-engineered mobile API.

There is no official public API. This talks to the same endpoints the
«Мой Киевстар» mobile app uses. Two surfaces are tried in order:

  1) The mobile API at  https://api-my.kyivstar.ua/  (preferred)
  2) The webapp API  at https://my.kyivstar.ua/api/  (fallback)

Auth flow (mobile):
   POST /idp/api/v1/mobile/auth  { "phone": "...", "password": "..." }
     → { "accessToken": "...", "refreshToken": "..." }
   Authorization: Bearer <accessToken>  on subsequent calls.

JWT lives ~30 min. We cache it in memory and refresh when expired.

If Киевстар changes the endpoints (they do every ~6 months), the surfaced
error will tell us what to patch — see `_dump_error` for hints.
"""
from __future__ import annotations

import time
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()


# Known Kyivstar API host candidates. We try each in order until one
# responds to /idp/api/v1/mobile/auth. The first hit gets cached for
# subsequent calls.
_BASE_CANDIDATES = (
    "https://mobapi.kyivstar.ua",
    "https://api.kyivstar.ua",
    "https://api-my.kyivstar.ua",
    "https://my.kyivstar.ua",
    "https://www.kyivstar.ua",
)

_AUTH_PATH_CANDIDATES = (
    "/idp/api/v1/mobile/auth",
    "/api/v1/mobile/auth",
    "/api/v1/auth/login",
    "/api/auth/login",
    "/idp/api/v1/auth",
)

_DASHBOARD_PATH_CANDIDATES = (
    "/dashboard/api/v1/info",
    "/api/v1/dashboard",
    "/api/v1/info",
    "/api/v1/profile",
    "/api/v1/me",
)

_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 "
    "KyivstarMobileApp/4.5.0"
)


class KyivstarError(RuntimeError):
    pass


class KyivstarClient:
    def __init__(self, phone: str, password: str) -> None:
        self.phone = (phone or "").strip().lstrip("+")
        self.password = password or ""
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        # Cached endpoints once we find a working combo
        self._auth_url: str | None = None
        self._dashboard_url: str | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> "KyivstarClient | None":
        phone = getattr(settings, "kyivstar_phone", "") or ""
        password = getattr(settings, "kyivstar_password", "") or ""
        if not phone or not password:
            return None
        return cls(phone, password)

    # ─── Auth ────────────────────────────────────────────────────

    async def _ensure_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        payload = {"phone": self.phone, "password": self.password}
        headers = {"User-Agent": _USER_AGENT, "Content-Type": "application/json"}

        # Use cached working endpoint if we've discovered it before
        urls_to_try: list[str] = []
        if self._auth_url:
            urls_to_try.append(self._auth_url)
        else:
            for base in _BASE_CANDIDATES:
                for path in _AUTH_PATH_CANDIDATES:
                    urls_to_try.append(f"{base}{path}")

        attempts: list[str] = []
        data: dict | None = None
        chosen_url: str | None = None

        for url in urls_to_try:
            try:
                async with session.post(
                    url, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    body_text = await resp.text()
                    if resp.status >= 400:
                        attempts.append(f"{url} → {resp.status}")
                        continue
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        attempts.append(f"{url} → 200 non-json")
                        continue
                    chosen_url = url
                    break
            except aiohttp.ClientError as e:
                attempts.append(f"{url} → {type(e).__name__}")
                continue
            except Exception as e:
                attempts.append(f"{url} → {type(e).__name__}: {str(e)[:60]}")
                continue

        if data is None:
            raise KyivstarError(
                "ни один auth-endpoint не ответил. Пробовал:\n"
                + "\n".join(attempts[:12])
            )

        token = (
            data.get("accessToken")
            or data.get("access_token")
            or data.get("token")
            or (data.get("data") or {}).get("accessToken")
        )
        if not token:
            raise KyivstarError(f"auth ок но без токена: {str(data)[:200]}")

        self._token = token
        self._auth_url = chosen_url
        self._token_expires_at = time.time() + int(data.get("expiresIn", 1700))
        log.info("kyivstar_authenticated", url=chosen_url)
        return token

    # ─── Public API ──────────────────────────────────────────────

    async def balance(self) -> dict:
        """Return parsed personal-account snapshot:
        { balance_uah, minutes_remaining, gb_remaining, sms_remaining,
          tariff, next_charge_date, raw }
        Raises KyivstarError on auth/parse failures."""
        async with aiohttp.ClientSession() as session:
            token = await self._ensure_token(session)
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": _USER_AGENT,
            }

            # The auth URL we discovered tells us the base; the dashboard
            # very likely lives on the same host. Try its known paths.
            urls_to_try: list[str] = []
            if self._dashboard_url:
                urls_to_try.append(self._dashboard_url)
            elif self._auth_url:
                base = self._auth_url.split("/", 3)
                base = "/".join(base[:3])  # scheme://host
                for path in _DASHBOARD_PATH_CANDIDATES:
                    urls_to_try.append(f"{base}{path}")

            data: dict | None = None
            attempts: list[str] = []
            chosen_url: str | None = None

            for url in urls_to_try:
                try:
                    async with session.get(
                        url, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status >= 400:
                            attempts.append(f"{url} → {resp.status}")
                            continue
                        try:
                            data = await resp.json(content_type=None)
                        except Exception:
                            attempts.append(f"{url} → 200 non-json")
                            continue
                        chosen_url = url
                        break
                except aiohttp.ClientError as e:
                    attempts.append(f"{url} → {type(e).__name__}")
                    continue

            if data is None:
                raise KyivstarError(
                    "auth ок, но dashboard endpoint не отвечает. Попытки:\n"
                    + "\n".join(attempts[:8])
                )
            self._dashboard_url = chosen_url

        return self._parse_dashboard(data)

    @staticmethod
    def _parse_dashboard(data: dict) -> dict:
        """Extract a normalized snapshot regardless of where exactly the
        Киевстар response puts each field — they like to rename things
        between releases. We probe multiple key paths."""
        def _pick(keys: list[str], src: dict | None = None) -> Any:
            cur = src if src is not None else data
            for path in keys:
                node: Any = cur
                ok = True
                for p in path.split("."):
                    if isinstance(node, dict) and p in node:
                        node = node[p]
                    else:
                        ok = False
                        break
                if ok and node not in (None, "", []):
                    return node
            return None

        balance_uah = _pick([
            "balance.amount", "balance.value", "balance",
            "account.balance.amount", "money.amount",
        ])
        minutes = _pick([
            "minutes.remaining", "minutes.amount", "voice.remaining",
            "packs.minutes", "remaining.minutes",
        ])
        gb = _pick([
            "internet.remaining", "internet.amount", "data.remaining",
            "traffic.remaining", "packs.internet", "remaining.data",
        ])
        sms = _pick([
            "sms.remaining", "sms.amount", "packs.sms", "remaining.sms",
        ])
        tariff = _pick([
            "tariff.name", "tariff", "plan.name", "package.name",
        ])
        next_charge = _pick([
            "tariff.nextCharge", "tariff.nextChargeDate",
            "package.nextRenewalDate", "subscription.nextChargeDate",
        ])

        return {
            "balance_uah": balance_uah,
            "minutes_remaining": minutes,
            "gb_remaining": gb,
            "sms_remaining": sms,
            "tariff": tariff,
            "next_charge_date": next_charge,
            "raw": data,
        }


def format_snapshot(snap: dict) -> str:
    """Telegram-friendly HTML for chat reply."""
    lines = ["📱 <b>Мой Киевстар</b>"]
    if snap.get("tariff"):
        lines.append(f"🏷 Тариф: <b>{snap['tariff']}</b>")
    if snap.get("balance_uah") is not None:
        lines.append(f"💰 Баланс: <b>{snap['balance_uah']} ₴</b>")
    if snap.get("gb_remaining") is not None:
        lines.append(f"🌐 Интернет: <b>{snap['gb_remaining']} ГБ</b>")
    if snap.get("minutes_remaining") is not None:
        lines.append(f"📞 Минуты: <b>{snap['minutes_remaining']}</b>")
    if snap.get("sms_remaining") is not None:
        lines.append(f"💬 SMS: <b>{snap['sms_remaining']}</b>")
    if snap.get("next_charge_date"):
        lines.append(f"🔁 Следующее списание: {snap['next_charge_date']}")
    if len(lines) == 1:
        lines.append("⚠️ Поля не распознаны — Киевстар сменил структуру ответа. См. devops логи.")
    return "\n".join(lines)
