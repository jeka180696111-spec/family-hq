"""Nova Poshta parcel poller.

Two ways parcels get into the `parcels` table:

1. Manual — the user pastes a 14-digit TTN in the family chat (or sends
   'Прораб, отследи ТТН XYZ'). main.py picks it up via regex and calls
   devops._parcel_track(). This always works (public API key only).

2. Auto-discovery — every 30 min, if NOVA_POSHTA_TOKEN_OAUTH2 is set,
   discover_incoming_parcels() calls the private-cabinet
   getIncomingDocumentsByPhone method (see nova_poshta.py) and inserts any
   TTN not already tracked, no manual paste needed. This is a reverse-
   engineered, undocumented endpoint — if NP breaks or the session token
   expires, this silently stops finding new parcels until the token is
   refreshed (the family gets a one-time heads-up in chat, not a repeat
   spam, on the first auth failure — see _auth_warned below).

Either way, once a TTN is in the table, poll_parcels() below takes over:
every 30 min it re-checks status and pushes a notification on change.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import insert, select
from sqlalchemy import update as sql_update

from src.db.models import Parcel
from src.utils.time import iso_now, now_kyiv

log = structlog.get_logger()

# In-memory only (resets on restart) — avoids re-sending the "token expired"
# warning every 30 minutes while nobody's refreshed it yet.
_auth_warned = False


_ARRIVED_KEYWORDS = ("прибула", "у відділенні", "прибыла", "в отделение", "ready for pickup")
_DELIVERED_KEYWORDS = ("отримано", "получено", "delivered", "видано")


def _is_arrived(status: str | None) -> bool:
    s = (status or "").lower()
    return any(k in s for k in _ARRIVED_KEYWORDS)


def _is_delivered(status: str | None) -> bool:
    s = (status or "").lower()
    return any(k in s for k in _DELIVERED_KEYWORDS)


async def poll_parcels(memory: Any, bot_manager: Any, chat_id: int,
                       calendar_client: Any = None) -> None:
    try:
        from src.config import get_settings
        from src.integrations.nova_poshta import NovaPoshtaClient
        settings = get_settings()
        client = NovaPoshtaClient.from_settings(settings)
        if not client:
            return

        async with memory._engine.connect() as conn:
            actives = list(await conn.execute(
                select(Parcel).where(Parcel.delivered_at.is_(None))
            ))

        for p in actives:
            try:
                fresh = await client.track(p.ttn)
            except Exception:
                log.exception("nova_recheck_failed", ttn=p.ttn)
                continue
            new_status = fresh.get("status")
            changed = (new_status and new_status != p.status)
            values: dict[str, Any] = {
                "status": new_status,
                "status_code": str(fresh.get("status_code") or ""),
                "last_checked_at": iso_now(),
            }
            if fresh.get("actual_delivery"):
                values["delivered_at"] = fresh["actual_delivery"]
            async with memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(Parcel).where(Parcel.id == p.id).values(**values)
                )
            if changed and bot_manager and chat_id:
                emoji = "📦"
                if _is_arrived(new_status):
                    emoji = "🎯"
                elif _is_delivered(new_status):
                    emoji = "✅"
                text = f"{emoji} <b>{p.title or p.ttn}</b>\n{new_status}"
                if fresh.get("warehouse"):
                    text += f"\n📍 {fresh.get('city_to')} · {fresh.get('warehouse')}"
                shipping = fresh.get("shipping_uah")
                cod = fresh.get("cod_uah")
                total = fresh.get("total_uah")
                if shipping or cod:
                    money_line = []
                    if shipping:
                        money_line.append(f"доставка {int(shipping)}₴")
                    if cod:
                        money_line.append(f"наложка {int(cod)}₴")
                    if cod and total and total != shipping:
                        money_line.append(f"всего {int(total)}₴")
                    text += "\n💰 " + " · ".join(money_line)
                if _is_arrived(new_status):
                    text += "\n⚠️ Забрать в течение 5 дней"
                    if calendar_client:
                        try:
                            start = now_kyiv() + timedelta(days=1)
                            start = start.replace(hour=18, minute=0)
                            await calendar_client.create_event(
                                title=f"📦 Забрать посылку: {p.title or p.ttn}",
                                start=start, end=start + timedelta(hours=1),
                                description=f"ТТН: {p.ttn}\n#parcel:{p.ttn}",
                                color_id="6",
                            )
                        except Exception:
                            log.exception("parcel_calendar_event_failed", ttn=p.ttn)
                try:
                    await bot_manager.send_message(
                        agent_id="devops", chat_id=chat_id, text=text,
                    )
                except Exception:
                    log.exception("parcel_push_failed", ttn=p.ttn)
    except Exception:
        log.exception("parcel_poll_tick_failed")


def register_parcel_poll_job(scheduler, memory, bot_manager, chat_id: int,
                             calendar_client: Any = None) -> None:
    scheduler.add_job(
        poll_parcels, "interval", minutes=30,
        args=[memory, bot_manager, chat_id, calendar_client],
        id="parcel_poll", replace_existing=True,
    )
    log.info("parcel_poll_registered")


async def discover_incoming_parcels(memory: Any, bot_manager: Any, chat_id: int) -> None:
    """Find new incoming parcels automatically, no TTN paste required.
    No-ops if NOVA_POSHTA_TOKEN_OAUTH2 isn't configured."""
    global _auth_warned
    try:
        from src.config import get_settings
        from src.integrations.nova_poshta import NovaPoshtaAuthError, NovaPoshtaClient
        settings = get_settings()
        oauth_token = getattr(settings, "nova_poshta_oauth_token", "")
        client = NovaPoshtaClient.from_settings(settings)
        if not client or not oauth_token:
            return

        now = now_kyiv()
        try:
            incoming = await client.list_incoming_by_phone(
                oauth_token,
                date_from=now - timedelta(days=90),
                date_to=now + timedelta(days=1),
            )
        except NovaPoshtaAuthError:
            log.warning("parcel_discovery_auth_expired")
            if not _auth_warned:
                _auth_warned = True
                if bot_manager and chat_id:
                    try:
                        await bot_manager.send_message(
                            agent_id="devops", chat_id=chat_id,
                            text=(
                                "⚠️ Токен Новой Почты (NOVA_POSHTA_TOKEN_OAUTH2) устарел — "
                                "автопоиск входящих посылок остановлен. Нужно заново достать "
                                "TokenOAuth2 из личного кабинета my.novaposhta.ua (DevTools → "
                                "Network → любой запрос к api.novaposhta.ua → Headers → "
                                "Request Headers → TokenOAuth2) и обновить переменную в Railway."
                            ),
                        )
                    except Exception:
                        log.exception("parcel_discovery_auth_notify_failed")
            return
        _auth_warned = False

        if not incoming:
            return

        async with memory._engine.connect() as conn:
            existing_ttns = {row.ttn for row in await conn.execute(select(Parcel.ttn))}

        for inv in incoming:
            ttn = (inv.get("Number") or "").strip()
            if not ttn or ttn in existing_ttns:
                continue
            existing_ttns.add(ttn)
            status = inv.get("TrackingStatusName") or ""
            title = inv.get("CargoDescription") or ""
            sender = inv.get("SenderName") or ""
            now_iso = iso_now()
            async with memory._engine.begin() as conn:
                await conn.execute(insert(Parcel).values(
                    carrier="nova_poshta", ttn=ttn,
                    title=title or None, member="family",
                    status=status, status_code=str(inv.get("TrackingStatusCode") or ""),
                    last_checked_at=now_iso, created_at=now_iso,
                ))
            if bot_manager and chat_id:
                text = f"📦 Новая посылка (авто): <b>{title or ttn}</b>\n{status}"
                if sender:
                    text += f"\nОт: {sender}"
                try:
                    await bot_manager.send_message(
                        agent_id="devops", chat_id=chat_id, text=text,
                    )
                except Exception:
                    log.exception("parcel_discovery_push_failed", ttn=ttn)
    except Exception:
        log.exception("parcel_discovery_tick_failed")


def register_parcel_discovery_job(scheduler, memory, bot_manager, chat_id: int) -> None:
    scheduler.add_job(
        discover_incoming_parcels, "interval", minutes=30,
        args=[memory, bot_manager, chat_id],
        id="parcel_discovery", replace_existing=True,
    )
    log.info("parcel_discovery_registered")
