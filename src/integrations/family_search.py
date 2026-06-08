"""Family-wide search: chat messages, baby diary, photos, fuel logs,
trips, family wiki, calendar events. Returns top results ordered by
recency or relevance.

Strategy: keyword + date filters across data sources, then LLM-ranked
top-N. Cheap, fast, no embeddings yet.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select

log = structlog.get_logger()


async def search_everywhere(
    query: str, memory: Any, sheets_client: Any = None,
    days_back: int = 365, limit_per_source: int = 6,
) -> dict:
    """Search across all data sources and return grouped results."""
    from src.utils.time import now_kyiv
    cutoff = (now_kyiv() - timedelta(days=days_back)).isoformat()
    q = query.strip().lower()
    tokens = [t for t in q.split() if len(t) >= 3]
    if not tokens:
        return {"error": "слишком короткий запрос"}

    out: dict = {"query": query, "groups": {}}

    # 1. Chat messages
    try:
        from src.db.models import Message
        async with memory._engine.connect() as conn:
            cond = or_(*[Message.text.ilike(f"%{t}%") for t in tokens])
            stmt = (
                select(Message).where(cond).where(Message.created_at >= cutoff)
                .order_by(Message.created_at.desc()).limit(limit_per_source)
            )
            rows = list(await conn.execute(stmt))
        out["groups"]["chat"] = [
            {
                "when": getattr(r, "created_at", ""),
                "from": getattr(r, "agent_id", None) or "user",
                "text": (getattr(r, "text", "") or "")[:200],
            }
            for r in rows
        ]
    except Exception:
        log.exception("search_chat_failed")

    # 2. Baby photos (by caption)
    try:
        from src.db.models import BabyPhoto
        async with memory._engine.connect() as conn:
            cond = or_(
                *[BabyPhoto.caption.ilike(f"%{t}%") for t in tokens],
                *[BabyPhoto.tags.ilike(f"%{t}%") for t in tokens],
            )
            rows = list(await conn.execute(
                select(BabyPhoto).where(cond)
                .order_by(BabyPhoto.id.desc()).limit(limit_per_source)
            ))
        out["groups"]["photos"] = [
            {
                "when": r.created_at, "age": r.age_label,
                "caption": r.caption, "drive_id": r.drive_file_id,
            }
            for r in rows
        ]
    except Exception:
        log.exception("search_photos_failed")

    # 3. Fuel logs
    try:
        from src.db.models import FuelLog
        async with memory._engine.connect() as conn:
            cond = or_(
                *[FuelLog.station.ilike(f"%{t}%") for t in tokens if FuelLog.station is not None],
                *[FuelLog.notes.ilike(f"%{t}%") for t in tokens],
            )
            rows = list(await conn.execute(
                select(FuelLog).where(cond)
                .order_by(FuelLog.id.desc()).limit(limit_per_source)
            ))
        out["groups"]["fuel"] = [
            {"when": r.created_at, "station": r.station, "liters": r.liters,
             "total": r.total_uah, "odo": r.odometer_km}
            for r in rows
        ]
    except Exception:
        log.exception("search_fuel_failed")

    # 4. Trips
    try:
        from src.db.models import Trip
        async with memory._engine.connect() as conn:
            cond = or_(
                *[Trip.origin.ilike(f"%{t}%") for t in tokens],
                *[Trip.destination.ilike(f"%{t}%") for t in tokens],
                *[Trip.notes.ilike(f"%{t}%") for t in tokens],
            )
            rows = list(await conn.execute(
                select(Trip).where(cond)
                .order_by(Trip.depart_at.desc()).limit(limit_per_source)
            ))
        out["groups"]["trips"] = [
            {"when": r.depart_at, "from": r.origin, "to": r.destination,
             "status": r.status, "distance_km": r.distance_km}
            for r in rows
        ]
    except Exception:
        log.exception("search_trips_failed")

    # 5. Family wiki
    try:
        from src.db.models import FamilyFact
        async with memory._engine.connect() as conn:
            cond = or_(
                *[FamilyFact.key.ilike(f"%{t}%") for t in tokens],
                *[FamilyFact.value.ilike(f"%{t}%") for t in tokens],
                *[FamilyFact.member.ilike(f"%{t}%") for t in tokens],
            )
            rows = list(await conn.execute(select(FamilyFact).where(cond)))
        out["groups"]["wiki"] = [
            {"member": r.member, "key": r.key, "value": r.value,
             "updated_at": r.updated_at}
            for r in rows
        ]
    except Exception:
        log.exception("search_wiki_failed")

    # 6. Baby diary (Sheets — if available)
    if sheets_client:
        try:
            from src.integrations.history_search import _search_sheet
            from src.utils.time import now_kyiv
            diary_cutoff = now_kyiv() - timedelta(days=min(days_back, 365))
            diary_rows = await _search_sheet(
                sheets_client, "Дневник", query, diary_cutoff, 50,
            )
            out["groups"]["diary"] = diary_rows[:limit_per_source]
        except Exception:
            log.exception("search_diary_failed")

    # 7. Calendar events
    out["groups"]["calendar"] = []  # filled by caller if calendar agent available

    return out
