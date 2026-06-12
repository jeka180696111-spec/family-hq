"""Poll Прораб's notebook every 5 minutes: any task whose due_at has
passed → ping Прораб in chat with a reminder so he can act on it
(turn the boiler on, send a message, …)."""
from __future__ import annotations

from typing import Any

import structlog

from src.integrations.prorab_notebook import list_tasks, mark_status, parse_due
from src.utils.time import now_kyiv

log = structlog.get_logger()


async def poll_notebook_overdue(
    agents: dict, memory: Any, bot_manager: Any, chat_id: int,
) -> None:
    nanny = agents.get("nanny")
    sheets = getattr(nanny, "_sheets", None) if nanny else None
    if not sheets:
        return

    try:
        tasks = await list_tasks(sheets, status="open")
    except Exception:
        log.exception("notebook_poll_failed_list")
        return

    now = now_kyiv()
    overdue = []
    for t in tasks:
        due = parse_due(t.get("due_at", ""))
        if due is None:
            continue
        if due > now:
            continue
        # Skip ones we've already pinged about (note marker)
        if "напомнено" in (t.get("note") or "").lower():
            continue
        overdue.append(t)

    if not overdue:
        return

    devops = agents.get("devops")
    if not (devops and bot_manager and chat_id):
        return

    lines = [f"⏰ <b>Просроченные задачи из блокнота ({len(overdue)})</b>"]
    for t in overdue[:10]:
        lines.append(
            f"◆ #{t['id']} {t['task']} (срок: {t['due_at']})"
        )
    lines.append(
        "\n🛠 Я их разберу: если автоматизируемые — выполню сейчас, "
        "остальные подтвержу или отложу."
    )

    try:
        await bot_manager.send_message(
            agent_id="devops", chat_id=chat_id, text="\n".join(lines),
        )
    except Exception:
        log.exception("notebook_overdue_notify_failed")

    # Mark each task as 'notified' by appending a note so we don't spam
    # the chat every 5 minutes about the same overdue items.
    for t in overdue[:10]:
        try:
            await mark_status(
                sheets, task_id=t["id"], status="open",
                note=f"⏰ напомнено в {now.strftime('%H:%M')}",
            )
        except Exception:
            log.exception("notebook_overdue_mark_failed", id=t["id"])
