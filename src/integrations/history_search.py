"""Архивариус: unified search across all family data sources.

Looks in:
  - Google Sheets «Дневник», «Здоровье», «Врач», «Прикорм», «Достижения»,
    «Рост», «Заметки»
  - SQLite: news_posts, shopping_list, message history

Any agent can call search_history(query, scope, days) — base agent exposes the tool.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from src.db.memory import SharedMemory
from src.db.models import NewsPost, ShoppingItem

log = structlog.get_logger()


_SCOPE_TO_SHEET = {
    "diary": "Дневник",
    "health": "Здоровье",
    "doctor": "Врач",
    "feeding": "Прикорм",
    "milestones": "Достижения",
    "growth": "Рост",
    "notes": "Заметки",
}


async def search_history(
    query: str,
    memory: SharedMemory,
    sheets_client: Any | None,
    scope: str = "all",
    days: int = 90,
    limit: int = 30,
) -> dict:
    """
    Returns matching rows across sources.

    scope: 'all' | 'diary' | 'health' | 'doctor' | 'feeding' | 'milestones' |
           'growth' | 'notes' | 'news' | 'shopping'
    """
    q = (query or "").lower().strip()
    results: dict[str, list[dict]] = {}
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Sheets sources
    if sheets_client and scope in ("all", "diary", "health", "doctor", "feeding", "milestones", "growth", "notes"):
        for scope_key, ws_name in _SCOPE_TO_SHEET.items():
            if scope not in ("all", scope_key):
                continue
            try:
                hits = await _search_sheet(sheets_client, ws_name, q, cutoff, limit)
                if hits:
                    results[scope_key] = hits
            except Exception:
                log.exception("history_sheet_search_failed", sheet=ws_name)

    # News posts
    if scope in ("all", "news"):
        try:
            async with memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(NewsPost)
                    .where(NewsPost.date >= cutoff.isoformat())
                    .order_by(NewsPost.date.desc())
                    .limit(500)
                ))
            news_hits = [
                {"date": r.date, "region": r.alert_region, "text": (r.text or "")[:300]}
                for r in rows
                if q in (r.text or "").lower()
            ][:limit]
            if news_hits:
                results["news"] = news_hits
        except Exception:
            log.exception("history_news_search_failed")

    # Shopping list
    if scope in ("all", "shopping"):
        try:
            async with memory._engine.connect() as conn:
                rows = list(await conn.execute(select(ShoppingItem)))
            shop_hits = [
                {
                    "item": r.item, "quantity": r.quantity, "place": r.place,
                    "done": bool(r.done_at), "added_at": r.added_at,
                }
                for r in rows
                if q in (r.item or "").lower()
                or (r.notes and q in r.notes.lower())
            ][:limit]
            if shop_hits:
                results["shopping"] = shop_hits
        except Exception:
            log.exception("history_shopping_search_failed")

    total = sum(len(v) for v in results.values())
    return {
        "query": query,
        "days": days,
        "scope": scope,
        "total_hits": total,
        "by_source": results,
    }


async def _search_sheet(sheets_client: Any, ws_name: str, q: str, cutoff: datetime, limit: int) -> list[dict]:
    """Generic substring search in a worksheet, filtered to rows newer than cutoff if date present."""
    ws = await sheets_client._open_worksheet(sheets_client._baby_sheet_id, ws_name)
    rows = await sheets_client._run_sync(ws.get_all_values)
    if not rows:
        return []
    header = rows[0]
    hits = []
    for row in rows[1:]:
        if not row:
            continue
        # Date column heuristic: first col containing DD.MM.YYYY-like
        row_date: datetime | None = None
        for cell in row:
            s = str(cell).strip()
            if len(s) == 10 and s.count(".") == 2:
                try:
                    row_date = datetime.strptime(s, "%d.%m.%Y")
                    break
                except ValueError:
                    continue
        if row_date is not None and row_date < cutoff:
            continue
        # Match if substring appears in any cell
        if not any(q in str(c).lower() for c in row):
            continue
        # Pack into dict with column names if header available
        rec = {}
        for i, c in enumerate(row):
            key = header[i].strip() if i < len(header) else f"col{i}"
            if c:
                rec[key] = c
        hits.append(rec)
        if len(hits) >= limit:
            break
    return hits
