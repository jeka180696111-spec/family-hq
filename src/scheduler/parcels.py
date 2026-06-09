"""Nova Poshta parcel poller — every 30 min checks active TTNs the user
has pasted into chat, pushes a notification on status change, marks
delivered_at when the parcel is received.

Discovery is manual: the user pastes a 14-digit TTN in the family chat
(or sends 'Прораб, отследи ТТН XYZ'). main.py picks it up via regex
and calls devops._parcel_track. From there this poller takes over.

Auto-discovery via getDocumentList was removed because NP's public API
only sees outgoing parcels, never incoming — useless for this family's
workflow.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy import update as sql_update

from src.db.models import Parcel
from src.utils.time import iso_now, now_kyiv

log = structlog.get_logger()


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
