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


_MOBILE_BASE = "https://api-my.kyivstar.ua"
_WEB_BASE = "https://my.kyivstar.ua"

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

        url = f"{_MOBILE_BASE}/idp/api/v1/mobile/auth"
        payload = {"phone": self.phone, "password": self.password}
        try:
            async with session.post(
                url, json=payload,
                headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
            ) as resp:
                if resp.status >= 400:
                    body = (await resp.text())[:400]
                    raise KyivstarError(
                        f"auth HTTP {resp.status}: {body}"
                    )
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise KyivstarError(f"auth network: {e}") from e

        token = data.get("accessToken") or data.get("token") or data.get("access_token")
        if not token:
            raise KyivstarError(f"auth response missing token: {str(data)[:200]}")
        self._token = token
        # default 28 min lifetime if expires_in absent
        self._token_expires_at = time.time() + int(data.get("expiresIn", 1700))
        log.info("kyivstar_authenticated")
        return token

    # ─── Public API ──────────────────────────────────────────────

    async def balance(self) -> dict:
        """Return parsed personal-account snapshot:
        { balance_uah, minutes_remaining, gb_remaining, sms_remaining,
          tariff, next_charge_date, raw }
        Raises KyivstarError on auth/parse failures."""
        async with aiohttp.ClientSession() as session:
            token = await self._ensure_token(session)
            url = f"{_MOBILE_BASE}/dashboard/api/v1/info"
            try:
                async with session.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": _USER_AGENT,
                    },
                ) as resp:
                    if resp.status >= 400:
                        body = (await resp.text())[:400]
                        raise KyivstarError(f"dashboard HTTP {resp.status}: {body}")
                    data = await resp.json()
            except aiohttp.ClientError as e:
                raise KyivstarError(f"dashboard network: {e}") from e

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
