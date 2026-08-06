"""Nova Poshta parcel poller.

Two ways parcels get into the `parcels` table:

1. Manual — the user pastes a 14-digit TTN in the family chat (or sends
   'Прораб, отследи ТТН XYZ'). main.py picks it up via regex and calls
   devops._parcel_track(). This always works (public API key only).

2. Auto-discovery — every 30 min, if NOVA_POSHTA_TOKEN_OAUTH2 is set,
   discover_incoming_parcels() calls the private-cabinet
   getIncomingDocumentsByPhone method (see nova_poshta.py) once per
   configured account/token and inserts any TTN not already tracked, no
   manual paste needed. This is a reverse-engineered, undocumented
   endpoint, and each token only sees parcels addressed to whoever's
   session it came from — if NP breaks it or a session token expires,
   that account's parcels silently stop being found until the token is
   refreshed (the family gets a one-time per-account heads-up in chat,
   not a repeat spam, on the first auth failure — see _auth_warned below).

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
# warning every 30 minutes while nobody's refreshed a given account's token.
_auth_warned: set[str] = set()


def _parse_oauth_tokens(raw: str) -> list[tuple[str, str]]:
    """"Имя:токен,Имя2:токен2" for several accounts, or a single bare token
    (auto-labelled "аккаунт N") when there's only one family member tracking."""
    out: list[tuple[str, str]] = []
    for i, part in enumerate((raw or "").split(","), start=1):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            label, token = part.split(":", 1)
            label, token = label.strip(), token.strip()
        else:
            label, token = f"аккаунт {i}", part
        if token:
            out.append((label, token))
    return out


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

        # Забираем все посылки не старше 45 дней (включая помеченные
        # delivered_at) — ретро-fix ниже разметит ошибочно скрытые:
        # раньше писали actual_delivery=время-прибытия-на-отделение в
        # delivered_at, из-за чего посылки на почте прятались.
        from datetime import timedelta as _td
        cutoff = (now_kyiv() - _td(days=45)).isoformat()
        async with memory._engine.connect() as conn:
            actives = list(await conn.execute(
                select(Parcel).where(Parcel.created_at >= cutoff)
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
                "city_from": fresh.get("city_from") or None,
                "city_to": fresh.get("city_to") or None,
                "warehouse": fresh.get("warehouse") or None,
                "weight_kg": fresh.get("weight_kg"),
                "cost_uah": fresh.get("total_uah"),
                "scheduled_at": fresh.get("scheduled_at") or None,
                "last_checked_at": iso_now(),
            }
            # ВАЖНО: `actual_delivery` от НП = дата прибытия НА отделение,
            # НЕ дата фактического получения. Отмечаем delivered_at ТОЛЬКО
            # когда статус явно «Отримано/Видано» — иначе прога прячет
            # посылки которые лежат на почте и ждут выдачи.
            if _is_delivered(new_status):
                values["delivered_at"] = fresh.get("actual_delivery") or iso_now()
            elif p.delivered_at:
                # Раньше могли ошибочно проставить — размаркать чтобы посылка
                # снова показалась (лежит на почте, ждёт выдачи)
                values["delivered_at"] = None
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
    """Find new incoming parcels automatically, no TTN paste required —
    once per configured account/token. No-ops if NOVA_POSHTA_TOKEN_OAUTH2
    isn't configured."""
    try:
        from src.config import get_settings
        from src.integrations.nova_poshta import NovaPoshtaAuthError, NovaPoshtaClient
        settings = get_settings()
        client = NovaPoshtaClient.from_settings(settings)
        accounts = _parse_oauth_tokens(getattr(settings, "nova_poshta_token_oauth2", ""))
        if not client or not accounts:
            return

        now = now_kyiv()
        async with memory._engine.connect() as conn:
            existing_ttns = {row.ttn for row in await conn.execute(select(Parcel.ttn))}

        for label, oauth_token in accounts:
            try:
                incoming = await client.list_incoming_by_phone(
                    oauth_token,
                    date_from=now - timedelta(days=90),
                    date_to=now + timedelta(days=1),
                )
            except NovaPoshtaAuthError:
                log.warning("parcel_discovery_auth_expired", account=label)
                if label not in _auth_warned:
                    _auth_warned.add(label)
                    if bot_manager and chat_id:
                        try:
                            await bot_manager.send_message(
                                agent_id="devops", chat_id=chat_id,
                                text=(
                                    f"⚠️ Токен Новой Почты «{label}» (NOVA_POSHTA_TOKEN_OAUTH2) устарел — "
                                    "автопоиск входящих посылок для этого аккаунта остановлен. Нужно "
                                    "заново достать TokenOAuth2 из личного кабинета my.novaposhta.ua "
                                    "(DevTools → Network → любой запрос к api.novaposhta.ua → Headers → "
                                    "Request Headers → TokenOAuth2) и обновить переменную в Railway."
                                ),
                            )
                        except Exception:
                            log.exception("parcel_discovery_auth_notify_failed", account=label)
                continue
            _auth_warned.discard(label)

            for inv in incoming:
                ttn = (inv.get("Number") or "").strip()
                if not ttn or ttn in existing_ttns:
                    continue
                existing_ttns.add(ttn)
                status = inv.get("TrackingStatusName") or ""
                title = inv.get("CargoDescription") or ""
                sender = inv.get("SenderName") or ""
                now_iso = iso_now()
                row = {
                    "carrier": "nova_poshta", "ttn": ttn,
                    "title": title or None, "member": label,
                    "status": status, "status_code": str(inv.get("TrackingStatusCode") or ""),
                    "last_checked_at": now_iso, "created_at": now_iso,
                }
                # Обогащаем маршрутом/весом/стоимостью сразу же через тот же
                # публичный track(), которым пользуется ручной режим — иначе
                # эти детали появились бы только через 30 мин, на следующем
                # тике poll_parcels().
                try:
                    enriched = await client.track(ttn)
                    if not enriched.get("error"):
                        row.update({
                            "city_from": enriched.get("city_from") or None,
                            "city_to": enriched.get("city_to") or None,
                            "warehouse": enriched.get("warehouse") or None,
                            "weight_kg": enriched.get("weight_kg"),
                            "cost_uah": enriched.get("total_uah"),
                            "scheduled_at": enriched.get("scheduled_at") or None,
                        })
                except Exception:
                    log.exception("parcel_discovery_enrich_failed", ttn=ttn)
                # Отмечаем delivered_at ТОЛЬКО по явному статусу «Отримано/
                # Видано». actual_delivery от НП — дата прибытия на отделение,
                # НЕ получения, ставить его в delivered_at неправильно
                # (посылки лежащие на почте прячутся из UI).
                if _is_delivered(row.get("status")):
                    row["delivered_at"] = enriched.get("actual_delivery") or now_iso
                async with memory._engine.begin() as conn:
                    await conn.execute(insert(Parcel).values(**row))
                if bot_manager and chat_id:
                    text = f"📦 Новая посылка (авто, {label}): <b>{title or ttn}</b>\n{status}"
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
