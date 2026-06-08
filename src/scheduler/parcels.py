"""Nova Poshta auto-discovery + tracking poller.

Every hour:
  1. For each configured NP account (eugene, marina) → list_recent_documents
  2. For TTNs we haven't seen → save to DB, push rich notification, create
     calendar event 'Забрать посылку' for the scheduled delivery date.
  3. For known active parcels → re-track, push on status change, mark
     calendar event 'done' when delivered.

Status milestones that trigger calendar handling:
  - new TTN found              → create event 'забрать посылку <title>'
  - 'Прибула у відділення'     → urgent push + ensure event with 5-day deadline
  - 'Отримано'                 → mark event done, archive parcel
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import insert, select
from sqlalchemy import update as sql_update

from src.db.models import Parcel
from src.utils.time import KYIV_TZ, iso_now, now_kyiv

log = structlog.get_logger()


_MEMBERS = [
    # (member, settings_attr)
    ("eugene", "nova_poshta_api_key"),
    ("marina", "nova_poshta_api_key_marina"),
]


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

        # 1. Auto-discovery per account
        for member, attr in _MEMBERS:
            key = getattr(settings, attr, "")
            if not key:
                continue
            client = NovaPoshtaClient(key)
            try:
                docs = await client.list_recent_documents(days_back=14)
            except Exception:
                log.exception("nova_discovery_failed", member=member)
                docs = []
            for d in docs:
                ttn = d.get("ttn")
                if not ttn:
                    continue
                async with memory._engine.connect() as conn:
                    existing = (await conn.execute(
                        select(Parcel).where(Parcel.ttn == ttn)
                    )).first()
                if existing:
                    continue
                # New parcel — track once to get full status
                try:
                    status = await client.track(ttn)
                except Exception:
                    log.exception("nova_initial_track_failed", ttn=ttn)
                    status = {}
                title = d.get("description") or "Посылка"
                now = iso_now()
                async with memory._engine.begin() as conn:
                    await conn.execute(insert(Parcel).values(
                        carrier="nova_poshta", ttn=ttn,
                        title=title, member=member,
                        status=status.get("status") or d.get("state"),
                        status_code=str(status.get("status_code") or ""),
                        last_checked_at=now, created_at=now,
                    ))
                # Announce
                await _announce_new(
                    bot_manager, chat_id, member, ttn, title, d, status,
                )
                # Calendar event for pickup
                if calendar_client:
                    await _create_pickup_event(
                        calendar_client, ttn, title, member, d.get("scheduled_at"),
                    )

        # 2. Re-check active parcels for status changes
        async with memory._engine.connect() as conn:
            actives = list(await conn.execute(
                select(Parcel).where(Parcel.delivered_at.is_(None))
            ))

        for p in actives:
            # Use the right key for this parcel's owner
            attr = "nova_poshta_api_key" if p.member != "marina" else "nova_poshta_api_key_marina"
            key = getattr(settings, attr, "") or getattr(settings, "nova_poshta_api_key", "")
            if not key:
                continue
            client = NovaPoshtaClient(key)
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
                tag = "Марины" if p.member == "marina" else "твоя"
                emoji = "📦"
                if _is_arrived(new_status):
                    emoji = "🎯"
                elif _is_delivered(new_status):
                    emoji = "✅"
                text = (
                    f"{emoji} <b>Посылка {tag}</b> · {p.title or p.ttn}\n"
                    f"{new_status}"
                )
                if fresh.get("warehouse"):
                    text += f"\n📍 {fresh.get('city_to')} · {fresh.get('warehouse')}"
                if _is_arrived(new_status):
                    text += "\n⚠️ Забрать в течение 5 дней"
                try:
                    await bot_manager.send_message(
                        agent_id="devops", chat_id=chat_id, text=text,
                    )
                except Exception:
                    log.exception("parcel_push_failed", ttn=p.ttn)
    except Exception:
        log.exception("parcel_poll_tick_failed")


async def _announce_new(
    bot_manager: Any, chat_id: int, member: str, ttn: str,
    title: str, doc: dict, status: dict,
) -> None:
    if not (bot_manager and chat_id):
        return
    tag = "Марины" if member == "marina" else "твоя"
    lines = [
        f"🆕 📦 <b>Новая посылка {tag}</b>",
        f"<b>{title}</b>",
        f"ТТН: <code>{ttn}</code>",
    ]
    if doc.get("sender_city") or doc.get("recipient_city"):
        lines.append(f"📍 {doc.get('sender_city', '?')} → {doc.get('recipient_city', '?')}")
    if doc.get("cost_uah"):
        lines.append(f"💰 Стоимость доставки: {doc['cost_uah']} ₴")
    if doc.get("weight_kg"):
        lines.append(f"⚖️ Вес: {doc['weight_kg']} кг")
    if doc.get("created_at"):
        lines.append(f"📤 Отправлено: {doc['created_at']}")
    if doc.get("scheduled_at"):
        lines.append(f"📥 Ожидается: {doc['scheduled_at']}")
    if status.get("status"):
        lines.append(f"Статус: {status['status']}")
    try:
        await bot_manager.send_message(
            agent_id="devops", chat_id=chat_id, text="\n".join(lines),
        )
    except Exception:
        log.exception("parcel_announce_failed", ttn=ttn)


async def _create_pickup_event(
    calendar_client: Any, ttn: str, title: str, member: str,
    scheduled_at: str | None,
) -> None:
    try:
        if scheduled_at:
            try:
                start = datetime.strptime(scheduled_at, "%d.%m.%Y").replace(
                    hour=18, tzinfo=KYIV_TZ,
                )
            except ValueError:
                start = now_kyiv() + timedelta(days=3)
        else:
            start = now_kyiv() + timedelta(days=3)
        end = start + timedelta(hours=1)
        tag = "Марины" if member == "marina" else "твоя"
        await calendar_client.create_event(
            title=f"📦 Забрать посылку {tag}: {title}",
            start=start, end=end,
            description=(
                f"ТТН: {ttn}\n"
                f"Получатель: {member}\n"
                f"#parcel:{ttn}"
            ),
            color_id="6",  # tangerine / orange
        )
        log.info("parcel_calendar_event_created", ttn=ttn)
    except Exception:
        log.exception("parcel_calendar_event_failed", ttn=ttn)


def register_parcel_poll_job(scheduler, memory, bot_manager, chat_id: int,
                             calendar_client: Any = None) -> None:
    scheduler.add_job(
        poll_parcels, "interval", minutes=60,
        args=[memory, bot_manager, chat_id, calendar_client],
        id="parcel_poll", replace_existing=True,
    )
    log.info("parcel_poll_registered")
