"""Background sync: Дневник Sheet → BabyState DB.

The diary is the source of truth — entries come from Няня, from
another bot, or from manual edits in Sheets. Every 5 min we compute
the current activity (sleep / walk / feed / diaper) from the latest
diary rows and project it into the BabyState row that the dashboard
and automations read.

Cheap: pulls ~2 days of rows, no Telegram, no LLM.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import insert, select
from sqlalchemy import update as sql_update

from src.db.models import BabyState
from src.integrations.baby_state_compute import compute_state_from_diary
from src.utils.time import iso_now

log = structlog.get_logger()


async def sync_baby_state(memory: Any, sheets_client: Any) -> None:
    if not sheets_client:
        return
    try:
        fresh = await compute_state_from_diary(sheets_client)
    except Exception:
        log.exception("baby_sync_compute_failed")
        return
    if not fresh:
        return
    fresh["updated_at"] = iso_now()
    try:
        async with memory._engine.begin() as conn:
            row = (await conn.execute(select(BabyState).where(BabyState.id == 1))).first()
            if row:
                await conn.execute(
                    sql_update(BabyState).where(BabyState.id == 1).values(**fresh)
                )
            else:
                await conn.execute(insert(BabyState).values(id=1, **fresh))
        log.info("baby_state_synced", keys=list(fresh.keys()))
    except Exception:
        log.exception("baby_sync_write_failed")


def register_baby_sync_job(scheduler, memory, sheets_client) -> None:
    if not sheets_client:
        log.info("baby_sync_skipped_no_sheets")
        return
    scheduler.add_job(
        sync_baby_state, "interval", minutes=5,
        args=[memory, sheets_client],
        id="baby_state_sync", replace_existing=True,
    )
    log.info("baby_sync_registered")
