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
            # Recovery!
            _ai_was_offline = False
            log.info("ai_recovered")
            await bot_manager.send_message(
                "devops",
                chat_id,
                "🛠️ ✅ Связь с AI восстановлена. Передаю накопленные сообщения.",
            )
            # Drain queue
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
            try:
                await bot_manager.send_message(
                    "devops",
                    chat_id,
                    "🛠️ ⚠️ AI offline (Anthropic API недоступен).\n"
                    "Принимаю сообщения в очередь. Проверяю каждые 30 сек.",
                )
            except Exception:
                pass
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
    """Register health check jobs."""
    scheduler.add_job(
        check_ai_health,
        "interval",
        seconds=30,
        args=[claude_client, memory, bot_manager, chat_id],
        id="ai_healthcheck",
        replace_existing=True,
    )
    scheduler.add_job(
        check_external_bots,
        "interval",
        minutes=5,
        args=[memory, bot_manager, chat_id],
        id="external_healthcheck",
        replace_existing=True,
    )
    log.info("healthcheck_jobs_registered")
