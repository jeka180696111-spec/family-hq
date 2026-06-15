"""Прораб's notebook — TWO Google Sheets tabs inside the baby spreadsheet:

  📋 Блокнот Прораба    — разовые задачи/обещания (что нужно сделать к сроку)
  ⚙️ Автоматизации     — постоянно работающие правила IF→THEN (с условиями)

The auto-tab is the user-facing source of truth for what's scheduled to
run. DB still stores the execution config; notebook is the readable
mirror Прораб and the user both look at.

Columns — 📋 Блокнот Прораба:
  A=id  B=Создано  C=Задача  D=Срок  E=Статус  F=Выполнено  G=Заметка

Columns — ⚙️ Автоматизации:
  A=Имя_правила      B=Включено
  C=Описание         D=Триггер (когда срабатывает)
  E=Действие         F=Cooldown_мин
  G=Создано          H=Последний_запуск
  I=Заметка
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from src.utils.time import KYIV_TZ, now_kyiv

log = structlog.get_logger()


# ─── Tasks tab ────────────────────────────────────────────────────────

WORKSHEET = "📋 Блокнот Прораба"
_WORKSHEET_ALIASES = (WORKSHEET, "Блокнот Прораба")
_HEADER = ["id", "Создано", "Задача", "Срок", "Статус", "Выполнено", "Заметка"]


# ─── Automations tab ──────────────────────────────────────────────────

RULES_WORKSHEET = "⚙️ Автоматизации"
_RULES_ALIASES = (RULES_WORKSHEET, "Автоматизации")
_RULES_HEADER = [
    "Имя", "Включено", "Описание", "Триггер",
    "Действие", "Cooldown_мин", "Создано", "Последний_запуск", "Заметка",
]


async def _ensure_worksheet(sheets: Any) -> Any:
    """Get or create the notebook worksheet inside the baby spreadsheet.
    Looks for any aliased name; only creates a new tab if NONE exist."""
    gc = await sheets._get_client()
    spreadsheet = await sheets._run_sync(gc.open_by_key, sheets._baby_sheet_id)

    def _build_or_get() -> Any:
        existing = {w.title: w for w in spreadsheet.worksheets()}
        for alias in _WORKSHEET_ALIASES:
            if alias in existing:
                return existing[alias]
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


# ─── Automations tab operations ───────────────────────────────────────

async def _ensure_rules_worksheet(sheets: Any) -> Any:
    gc = await sheets._get_client()
    spreadsheet = await sheets._run_sync(gc.open_by_key, sheets._baby_sheet_id)

    def _build_or_get() -> Any:
        existing = {w.title: w for w in spreadsheet.worksheets()}
        for alias in _RULES_ALIASES:
            if alias in existing:
                return existing[alias]
        ws_new = spreadsheet.add_worksheet(title=RULES_WORKSHEET, rows=200, cols=10)
        ws_new.append_row(_RULES_HEADER, value_input_option="USER_ENTERED")
        return ws_new

    return await sheets._run_sync(_build_or_get)


async def upsert_rule(
    sheets: Any, *, name: str, enabled: bool,
    description: str, trigger: str, action: str,
    cooldown_min: int, created_at: str = "",
    last_fired_at: str = "", note: str = "",
) -> dict:
    """Insert or update a rule row keyed by Имя."""
    ws = await _ensure_rules_worksheet(sheets)

    def _do() -> tuple[str, int]:
        rows = ws.get_all_values()
        created = created_at or now_kyiv().strftime("%Y-%m-%d %H:%M")
        new_row = [
            name,
            "✅" if enabled else "⏸",
            description,
            trigger,
            action,
            str(cooldown_min),
            created,
            last_fired_at,
            note,
        ]
        for idx, row in enumerate(rows[1:], start=2):
            if not row or not row[0]:
                continue
            if row[0] == name:
                ws.update(f"A{idx}:I{idx}", [new_row], value_input_option="USER_ENTERED")
                return "updated", idx
        ws.append_row(new_row, value_input_option="USER_ENTERED")
        return "added", len(ws.get_all_values())

    op, idx = await sheets._run_sync(_do)
    log.info("notebook_rule_upserted", name=name, op=op)
    return {"op": op, "row": idx, "name": name}


async def delete_rule(sheets: Any, name: str) -> bool:
    ws = await _ensure_rules_worksheet(sheets)

    def _do() -> bool:
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if not row or not row[0]:
                continue
            if row[0] == name:
                ws.delete_rows(idx)
                return True
        return False

    return await sheets._run_sync(_do)


async def clear_all_rules(sheets: Any) -> int:
    """Wipe every row from the rules tab (keeps the header). Returns count."""
    ws = await _ensure_rules_worksheet(sheets)

    def _do() -> int:
        rows = ws.get_all_values()
        # Number of data rows = total - 1 (header)
        n = max(0, len(rows) - 1)
        if n > 0:
            # Delete from bottom to top to keep indices valid
            for idx in range(len(rows), 1, -1):
                ws.delete_rows(idx)
        return n

    return await sheets._run_sync(_do)


async def list_rules_from_sheet(sheets: Any) -> list[dict]:
    ws = await _ensure_rules_worksheet(sheets)
    rows = await sheets._run_sync(ws.get_all_values)
    out = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        out.append({
            "name": row[0],
            "enabled": (row[1] if len(row) > 1 else "") == "✅",
            "description": row[2] if len(row) > 2 else "",
            "trigger": row[3] if len(row) > 3 else "",
            "action": row[4] if len(row) > 4 else "",
            "cooldown_min": row[5] if len(row) > 5 else "",
            "created_at": row[6] if len(row) > 6 else "",
            "last_fired_at": row[7] if len(row) > 7 else "",
            "note": row[8] if len(row) > 8 else "",
        })
    return out


_KNOWN_RULE_TYPES = frozenset({
    "datetime", "datetime_range", "time", "sensor",
    "alert_active", "alert_ended", "power_outage", "baby_sleeping",
    "and", "or",
    "device", "message", "set_mode", "tool", "ac_command",
})


def _normalize(d: dict | None) -> dict:
    """Mirror of devops._normalize_rule_dict — accepts wrapper-style,
    hybrid wrapper+siblings, and flat shapes. Kept in sync."""
    if not isinstance(d, dict):
        return d or {}
    if "type" in d:
        return d
    if len(d) == 1:
        key, val = next(iter(d.items()))
        if isinstance(val, dict):
            return {"type": key, **val}
    # Hybrid: {<type>: {<some_fields>}, <other_fields>}
    for key, val in d.items():
        if key in _KNOWN_RULE_TYPES and isinstance(val, dict):
            siblings = {k: v for k, v in d.items() if k != key}
            return {"type": key, **val, **siblings}
    # AC compound action — device + mode/temperature without action
    if isinstance(d.get("device"), str) and (
        "mode" in d or "temperature" in d or "fan_speed" in d or "speed" in d
    ) and "action" not in d:
        return {"type": "ac_command", **d}
    if "device" in d and "action" in d and isinstance(d.get("device"), str):
        return {"type": "device", **d}
    if "agent" in d and "text" in d:
        return {"type": "message", **d}
    if "mode" in d and "enabled" in d:
        return {"type": "set_mode", **d}
    if "agent" in d and "tool" in d:
        return {"type": "tool", **d}
    if "at" in d:
        return {"type": "datetime", **d}
    if "cron" in d:
        return {"type": "time", **d}
    if "metric" in d and "op" in d and "value" in d:
        return {"type": "sensor", **d}
    if "region" in d:
        st = (d.get("state") or "").lower()
        if st == "ended":
            return {"type": "alert_ended", **d}
        return {"type": "alert_active", **d}
    if "state" in d and d.get("state") in ("active", "ended"):
        return {"type": "power_outage", **d}
    return d


def describe_trigger(condition: dict) -> str:
    """Human-readable string for the rules tab Триггер column."""
    import json as _json
    condition = _normalize(condition)
    kind = (condition or {}).get("type", "")
    if kind == "datetime":
        return f"однократно {(condition.get('at') or '')[:16]}"
    if kind == "time":
        cron = condition.get("cron") or ""
        wd = condition.get("weekday")
        s = f"ежедневно в {cron}" if cron else f"в {condition.get('hour','?'):02d}:{condition.get('minute',0):02d}"
        return s + (f" по {wd}" if wd else "")
    if kind == "sensor":
        return f"датчик {condition.get('device','?')}.{condition.get('metric','?')} {condition.get('op','?')} {condition.get('value','?')}"
    if kind == "alert_active":
        return f"тревога активна в {condition.get('region','?')}"
    if kind == "alert_ended":
        return f"отбой тревоги в {condition.get('region','?')}"
    if kind == "power_outage":
        st = condition.get("state", "?")
        out = f"электричество: {st}"
        if condition.get("delay_min"):
            out += f", задержка {condition['delay_min']}мин"
        if condition.get("within_min"):
            out += f", в течение {condition['within_min']}мин"
        return out
    if kind == "baby_sleeping":
        m = condition.get("min_minutes")
        return f"Матвей спит ≥{m} мин" if m else "Матвей спит"
    if kind in ("and", "or"):
        return kind.upper() + ": " + " / ".join(describe_trigger(r) for r in (condition.get("rules") or []))
    # Unknown shape — surface the raw JSON so the user can see what
    # the LLM actually produced. Far more useful than a silent "?".
    try:
        raw = _json.dumps(condition, ensure_ascii=False)
    except Exception:
        raw = str(condition)
    return f"⚠️ нераспозн.: {raw[:140]}"


def describe_action(action: dict) -> str:
    import json as _json
    action = _normalize(action)
    kind = (action or {}).get("type", "")
    if kind == "device":
        return f"{action.get('device','?')} → {action.get('action','?')}"
    if kind == "message":
        return f"сообщение от {action.get('agent','devops')}: {(action.get('text','') or '')[:60]}"
    if kind == "set_mode":
        return f"режим «{action.get('mode','?')}» = {action.get('enabled')}"
    if kind == "tool":
        return f"вызов tool {action.get('tool','?')} у {action.get('agent','?')}"
    if kind == "ac_command":
        bits = [action.get("device", "?")]
        if action.get("mode"):
            bits.append(str(action["mode"]))
        if action.get("temperature") is not None:
            bits.append(f"{action['temperature']}°")
        if action.get("fan_speed") or action.get("speed"):
            bits.append(f"вент. {action.get('fan_speed') or action.get('speed')}")
        return " · ".join(bits)
    try:
        raw = _json.dumps(action, ensure_ascii=False)
    except Exception:
        raw = str(action)
    return f"⚠️ нераспозн.: {raw[:140]}"


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
