"""Compute baby's current state (sleep / walk / feed / diaper) directly
from the Дневник Google Sheet.

The Sheet is the source of truth — entries may come from Няня, from a
different bot, or from manual edits. We rely on it instead of the
projected BabyState table so the dashboard always reflects reality.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger()


_SLEEP_START = ("уснул", "уснула", "заснул", "лёг", "лег", "начал спать", "спит",
                "пошёл спать", "пошел спать", "укладыва", "отбой")
_SLEEP_END = ("проснул", "встал", "разбудил", "просыпан", "не спит", "подъём", "подьем")

_WALK_START = ("вышли", "вышел", "вышла", "выехали", "пошли гулять", "идём гулять",
               "идем гулять", "началась прогулк", "на прогулк", "стартовали")
_WALK_END = ("вернулись", "вернулся", "пришли", "пришёл", "пришла", "приехали",
             "конец прогулк", "закончили", "дома")


def _entry_dt(row_data: dict):
    from datetime import datetime, timezone
    date_s = (row_data.get("date") or "").strip()
    time_s = (row_data.get("time") or "00:00").strip()
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{date_s} {time_s}", fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _kind_clean(cell: str) -> str:
    """Strip leading emoji from a 'kind' cell."""
    cleaned = cell or ""
    for ch in cell or "":
        if ch.isalpha():
            break
        cleaned = cleaned[1:]
    return cleaned.strip().lower()


def _match(event_text: str, keywords: tuple[str, ...]) -> bool:
    e = (event_text or "").lower()
    return any(k in e for k in keywords)


async def compute_state_from_diary(sheets_client: Any) -> dict:
    """Return a baby_state-like dict computed from the latest Дневник entries.

    Looks at the last ~36 hours so we catch any current sleep / walk.
    """
    if not sheets_client:
        return {}
    try:
        rows = await sheets_client.get_baby_diary(days=2)
    except Exception:
        log.exception("baby_state_compute_diary_failed")
        return {}
    parsed = []
    for r in rows:
        d = r.data
        dt = _entry_dt(d)
        if dt is None:
            continue
        parsed.append({
            "dt": dt,
            "kind": _kind_clean(d.get("kind", "")),
            "event": (d.get("event") or "").strip(),
        })
    parsed.sort(key=lambda x: x["dt"])

    state: dict = {}

    # Last sleep transition
    for it in reversed(parsed):
        if it["kind"] in ("сон", "sleep"):
            if _match(it["event"], _SLEEP_END):
                state["sleeping_since"] = None
                state["awake_since"] = it["dt"].isoformat()
            elif _match(it["event"], _SLEEP_START):
                state["sleeping_since"] = it["dt"].isoformat()
                state["awake_since"] = None
            else:
                # Generic sleep write — assume start if no prior sleep_end after this
                state["sleeping_since"] = it["dt"].isoformat()
                state["awake_since"] = None
            break

    # Last walk transition
    for it in reversed(parsed):
        if it["kind"] in ("прогулка", "поездка", "walk", "trip"):
            if _match(it["event"], _WALK_END):
                state["walking_since"] = None
                state["walk_ended_at"] = it["dt"].isoformat()
            elif _match(it["event"], _WALK_START):
                state["walking_since"] = it["dt"].isoformat()
                state["walk_ended_at"] = None
            else:
                state["walking_since"] = it["dt"].isoformat()
                state["walk_ended_at"] = None
            break

    # Last feed
    for it in reversed(parsed):
        if it["kind"] in ("еда", "food", "прикорм"):
            state["last_feed_at"] = it["dt"].isoformat()
            break

    # Last diaper
    for it in reversed(parsed):
        if it["kind"] in ("подгузник", "diaper"):
            state["last_diaper_at"] = it["dt"].isoformat()
            break

    return state
