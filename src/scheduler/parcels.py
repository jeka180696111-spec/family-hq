"""Background poller — checks active Nova Poshta parcels every 30 min
and pushes a notification when status changes (especially when delivered)."""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy import update as sql_update

from src.db.models import Parcel
from src.utils.time import iso_now

log = structlog.get_logger()


async def poll_parcels(memory: Any, bot_manager: Any, chat_id: int) -> None:
    try:
        from src.config import get_settings
        from src.integrations.nova_poshta import NovaPoshtaClient
        client = NovaPoshtaClient.from_settings(get_settings())
        if not client:
            return
        async with memory._engine.connect() as conn:
            actives = list(await conn.execute(
                select(Parcel).where(Parcel.delivered_at.is_(None))
            ))
        for p in actives:
            try:
                fresh = await client.track(p.ttn)
                new_status = fresh.get("status")
                new_code = str(fresh.get("status_code") or "")
                changed = (new_status and new_status != p.status)
                values = {
                    "status": new_status, "status_code": new_code,
                    "last_checked_at": iso_now(),
                }
                if fresh.get("actual_delivery"):
                    values["delivered_at"] = fresh["actual_delivery"]
                async with memory._engine.begin() as conn:
                    await conn.execute(
                        sql_update(Parcel).where(Parcel.id == p.id).values(**values)
                    )
                if changed and bot_manager and chat_id:
                    label = p.title or p.ttn
                    text = f"📦 <b>{label}</b>\n{new_status}"
                    if fresh.get("warehouse"):
                        text += f"\n📍 {fresh.get('city_to')} · {fresh.get('warehouse')}"
                    try:
                        await bot_manager.send_message(
                            agent_id="devops", chat_id=chat_id, text=text,
                        )
                    except Exception:
                        log.exception("parcel_push_failed", ttn=p.ttn)
            except Exception:
                log.exception("parcel_check_failed", ttn=p.ttn)
    except Exception:
        log.exception("parcel_poll_tick_failed")


def register_parcel_poll_job(scheduler, memory, bot_manager, chat_id: int) -> None:
    scheduler.add_job(
        poll_parcels, "interval", minutes=30,
        args=[memory, bot_manager, chat_id],
        id="parcel_poll", replace_existing=True,
    )
    log.info("parcel_poll_registered")
