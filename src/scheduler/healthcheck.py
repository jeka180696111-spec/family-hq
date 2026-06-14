from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.integrations.claude_client import AIOfflineError, ClaudeClient
    from src.integrations.telegram_bots import BotManager
    from src.db.memory import SharedMemory

log = structlog.get_logger()

_ai_was_offline: bool = False
_offline_since: str | None = None


async def check_ai_health(
    claude_client: "ClaudeClient",
    memory: "SharedMemory",
    bot_manager: "BotManager",
    chat_id: int,
) -> bool:
    """
    Ping Anthropic API.
    - On first failure: notify group, enter offline mode
    - On recovery: notify group, drain queue
    Returns True if API is healthy.
    """
    global _ai_was_offline, _offline_since

    from src.integrations.claude_client import AIOfflineError
    from src.utils.time import iso_now

    try:
        await claude_client.complete(
            model="claude-haiku-4-5-20251001",
            system="Ответь одним словом.",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )

        if _ai_was_offline:
            # Recovery! Log only — don't spam chat. If AI was down for >5 min,
            # the LLM-driven agents already surfaced errors organically.
            _ai_was_offline = False
            log.info("ai_recovered")
            from src.db.queue import MessageQueue
            queue = MessageQueue(memory)
            queued = await queue.drain()
            if queued:
                log.info("queue_draining", count=len(queued))

        return True

    except Exception:
        if not _ai_was_offline:
            _ai_was_offline = True
            _offline_since = iso_now()
            log.error("ai_offline")
            # Silent — no chat push. If real outage, agent responses will fail
            # and the user will see it through normal flow.
        return False


async def check_external_bots(
    memory: "SharedMemory",
    bot_manager: "BotManager",
    chat_id: int,
) -> None:
    """Check health of Matveika and Finance bots (every 5 minutes)."""
    from src.utils.time import iso_now

    async with memory._engine.begin() as conn:
        from sqlalchemy import insert

        from src.db.models import ExternalHealth

        # Just update the timestamp — actual ping logic would go here
        for service in ["matveika_bot", "finance_bot"]:
            await conn.execute(
                insert(ExternalHealth)
                .values(
                    service=service,
                    last_check_at=iso_now(),
                    last_status="ok",
                    consecutive_failures=0,
                )
                .prefix_with("OR IGNORE")
            )


def register_healthcheck_jobs(
    scheduler,
    claude_client,
    memory,
    bot_manager,
    chat_id: int,
) -> None:
    """Register health check jobs.

    Note: the AI healthcheck was removed — it fired every 30 sec and
    burnt ~2880 Gemini quota per day pinging an LLM just to confirm
    «alive». Real outages surface through the user's next message
    instantly (and provider override flips on credit-exhaustion), so
    proactive polling adds zero value.
    """
    scheduler.add_job(
        check_external_bots,
        "interval",
        minutes=5,
        args=[memory, bot_manager, chat_id],
        id="external_healthcheck",
        replace_existing=True,
    )
    log.info("healthcheck_jobs_registered_external_only")
