"""Прораб's notebook — a Google Sheet where devops jots down promises,
deferred tasks, and reminders so the LLM doesn't have to remember them
across sessions. Backed by the same baby spreadsheet (so we don't need a
separate Drive file or auth).

Columns:  A=id  B=Создано  C=Задача  D=Срок (ISO Kyiv)  E=Статус  F=Выполнено  G=Заметка

Statuses:
  open  — pending
  done  — completed
  skip  — cancelled / no longer relevant
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from src.utils.time import KYIV_TZ, now_kyiv

log = structlog.get_logger()


WORKSHEET = "📋 Блокнот Прораба"
_HEADER = ["id", "Создано", "Задача", "Срок", "Статус", "Выполнено", "Заметка"]


async def _ensure_worksheet(sheets: Any) -> Any:
    """Get or create the notebook worksheet inside the baby spreadsheet."""
    gc = await sheets._get_client()
    spreadsheet = await sheets._run_sync(gc.open_by_key, sheets._baby_sheet_id)

    def _build_or_get() -> Any:
        try:
            return spreadsheet.worksheet(WORKSHEET)
        except Exception:
            ws_new = spreadsheet.add_worksheet(title=WORKSHEET, rows=200, cols=8)
            ws_new.append_row(_HEADER, value_input_option="USER_ENTERED")
            return ws_new

    return await sheets._run_sync(_build_or_get)


async def add_task(
    sheets: Any, task: str, due_at: str = "", note: str = "",
) -> dict:
    """Append a new task. due_at is ISO format in Kyiv tz, or '' if no deadline."""
    ws = await _ensure_worksheet(sheets)

    def _append() -> tuple[int, int]:
        rows = ws.get_all_values()
        next_id = 1
        for row in reversed(rows[1:]):
            if not row:
                continue
            try:
                next_id = int(row[0]) + 1
                break
            except (ValueError, TypeError, IndexError):
                continue
        ws.append_row(
            [
                str(next_id),
                now_kyiv().strftime("%Y-%m-%d %H:%M"),
                task,
                due_at,
                "open",
                "",
                note,
            ],
            value_input_option="USER_ENTERED",
        )
        return next_id, len(ws.get_all_values())

    task_id, row_index = await sheets._run_sync(_append)
    log.info("notebook_task_added", id=task_id, task=task[:60])
    return {"id": task_id, "row": row_index, "task": task, "due_at": due_at}


async def list_tasks(sheets: Any, status: str | None = "open") -> list[dict]:
    ws = await _ensure_worksheet(sheets)
    rows = await sheets._run_sync(ws.get_all_values)
    out = []
    for row in rows[1:]:
        if len(row) < 5 or not row[0]:
            continue
        try:
            tid = int(row[0])
        except (ValueError, TypeError):
            continue
        row_status = row[4] if len(row) > 4 else ""
        if status and row_status != status:
            continue
        out.append({
            "id": tid,
            "created_at": row[1] if len(row) > 1 else "",
            "task": row[2] if len(row) > 2 else "",
            "due_at": row[3] if len(row) > 3 else "",
            "status": row_status,
            "completed_at": row[5] if len(row) > 5 else "",
            "note": row[6] if len(row) > 6 else "",
        })
    return out


async def mark_status(sheets: Any, task_id: int, status: str, note: str = "") -> dict:
    ws = await _ensure_worksheet(sheets)

    def _update() -> bool:
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if not row or not row[0]:
                continue
            try:
                if int(row[0]) != task_id:
                    continue
            except (ValueError, TypeError):
                continue
            ws.update_cell(idx, 5, status)
            if status == "done":
                ws.update_cell(idx, 6, now_kyiv().strftime("%Y-%m-%d %H:%M"))
            if note:
                existing = row[6] if len(row) > 6 else ""
                merged = f"{existing}; {note}" if existing else note
                ws.update_cell(idx, 7, merged)
            return True
        return False

    ok = await sheets._run_sync(_update)
    return {"id": task_id, "updated": ok, "status": status}


def parse_due(due_at: str) -> datetime | None:
    if not due_at:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(due_at.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KYIV_TZ)
            return dt
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(due_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KYIV_TZ)
        return dt
    except Exception:
        return None
