from __future__ import annotations
"""Family HQ — main entry point."""

import argparse
import asyncio
import signal
import sys
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import get_settings
from src.utils.logging import setup_logging
from src.db.migrations import init_db
from src.db.memory import SharedMemory
from src.integrations.claude_client import ClaudeClient, AIOfflineError
from src.integrations.telegram_bots import BotManager
from src.integrations.telegram_user import UserBot
from src.integrations.sheets import SheetsClient
from src.integrations.gcalendar import CalendarClient
from src.integrations.github_api import GitHubClient
from src.integrations.web_search import WebSearchClient
from src.orchestrator.dispatcher import Dispatcher
from src.orchestrator.parser import MessageParser
from src.orchestrator.conversation import ConversationContext
from src.orchestrator.access_control import AccessControl
from src.orchestrator.registry import AgentRegistry
from src.agents.nanny import NannyAgent
from src.agents.news import NewsAgent
from src.agents.calendar import CalendarAgent
from src.agents.cook import CookAgent
from src.agents.health import HealthAgent
from src.agents.devops import DevOpsAgent
from src.scheduler.digest import register_digest_job
from src.scheduler.backup import register_backup_job
from src.scheduler.healthcheck import register_healthcheck_jobs
from src.scheduler.reminders import register_reminder_jobs

log = structlog.get_logger()

_shutdown_event: asyncio.Event | None = None


async def handle_new_message(
    message: Any,
    dispatcher: Dispatcher,
    parser: MessageParser,
    agents: dict[str, Any],
    registry: AgentRegistry,
    access_control: AccessControl,
    memory: SharedMemory,
    settings: Any,
    dry_run: bool = False,
) -> None:
    """
    Main message handler. Called for every new message in the group.
    1. Check authorization
    2. Save to memory
    3. Dispatch to agents
    4. Each agent handles and responds
    """
    try:
        # Skip messages from bots (they have bot tokens)
        if getattr(message, "via_bot", None) or (
            hasattr(message, "sender") and
            getattr(getattr(message, "sender", None), "bot", False)
        ):
            return

        user_id = getattr(message, "sender_id", None)
        text = getattr(message, "text", "") or ""
        message_id = getattr(message, "id", 0)

        if not text.strip():
            return

        # Authorization check
        if user_id and not access_control.is_owner(user_id):
            log.warning("unauthorized_message", user_id=user_id)
            return

        log.info("message_received", user_id=user_id, text=text[:50])

        # Save to shared memory
        chat_id = settings.hq_chat_id
        context = ConversationContext(memory, chat_id)
        await context.save_message(
            tg_message_id=message_id,
            user_id=user_id,
            agent_id=None,
            text=text,
        )

        if dry_run:
            log.info("dry_run_skipping_dispatch", text=text[:50])
            return

        # Get sender name
        sender = getattr(message, "sender", None)
        sender_name = (
            getattr(sender, "first_name", None) or
            getattr(sender, "username", None) or
            "Пользователь"
        )

        # Dispatch to agents
        recent = await context.get_recent(5)
        result = await dispatcher.dispatch(
            message_text=text,
            sender_name=sender_name,
            active_agent_ids=registry.active_ids(),
            recent_context=recent,
        )

        # Parse message for structured actions
        parsed = await parser.parse(text)

        # Execute each assigned agent (sorted by priority)
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        sorted_tasks = sorted(result.tasks, key=lambda t: priority_order.get(t.priority, 99))

        for task in sorted_tasks:
            agent = agents.get(task.agent_id)
            if not agent:
                log.warning("agent_not_found", agent_id=task.agent_id)
                continue

            try:
                await agent.handle(
                    message_text=text,
                    sender_name=sender_name,
                    context=context,
                    parsed_actions=[a.model_dump() for a in parsed.actions],
                )
            except Exception:
                log.exception("agent_handle_failed", agent_id=task.agent_id)

    except Exception:
        log.exception("message_handler_error")


async def run(dry_run: bool = False) -> None:
    """Main application runner."""
    settings = get_settings()
    setup_logging(settings.log_level)

    log.info("family_hq_starting", dry_run=dry_run)

    # Init DB
    engine = await init_db(settings.db_path)
    memory = SharedMemory(engine)

    # Init integrations
    claude = ClaudeClient(
        primary_key=settings.anthropic_api_key_primary,
        backup_key=settings.anthropic_api_key_backup,
    )

    bot_manager = BotManager()

    # Google integrations (only if credentials available)
    sa_info = settings.google_service_account_json

    sheets = None
    if sa_info and settings.sheet_baby_id:
        sheets = SheetsClient(sa_info, settings.sheet_baby_id, "")

    calendar_client = None
    if sa_info and settings.calendar_id:
        calendar_client = CalendarClient(sa_info, settings.calendar_id)

    github = None
    if settings.github_token:
        github = GitHubClient(settings.github_token, settings.github_repo)

    web_search = WebSearchClient()

    # Register all bots (6 internal agents; Фінн is external)
    agent_tokens = {
        "nanny": settings.nanny_bot_token,
        "news": settings.news_bot_token,
        "calendar": settings.calendar_bot_token,
        "cook": settings.cook_bot_token,
        "health": settings.health_bot_token,
        "devops": settings.devops_bot_token,
    }
    for agent_id, token in agent_tokens.items():
        if token:
            await bot_manager.register(agent_id, token)

    # Create agents
    chat_id = settings.hq_chat_id
    base_args = dict(claude_client=claude, bot_manager=bot_manager, memory=memory, chat_id=chat_id)

    agents: dict[str, Any] = {
        "nanny": NannyAgent(**base_args, sheets_client=sheets),
        "news": NewsAgent(**base_args),
        "calendar": CalendarAgent(**base_args, calendar_client=calendar_client),
        "cook": CookAgent(**base_args, web_search=web_search),
        "health": HealthAgent(**base_args),
        "devops": DevOpsAgent(**base_args, github_client=github),
    }

    # Load registry from DB
    registry = await AgentRegistry.load_from_db(memory)

    # Access control
    access_control = AccessControl(memory, settings.owner_ids)

    # Orchestrator
    dispatcher = Dispatcher(claude, settings.model_cheap)
    parser = MessageParser(claude, settings.model_cheap)

    # Scheduler
    scheduler = AsyncIOScheduler()
    register_digest_job(scheduler, agents["news"], memory, settings.digest_time)
    register_backup_job(scheduler, memory, settings.db_path, settings.drive_backup_folder_id, sa_info or {})
    register_healthcheck_jobs(scheduler, claude, memory, bot_manager, chat_id)
    register_reminder_jobs(scheduler, agents["calendar"], bot_manager, chat_id, memory)
    scheduler.start()

    if dry_run:
        log.info("dry_run_mode_all_systems_initialized")
        await asyncio.sleep(2)
        scheduler.shutdown(wait=False)
        await bot_manager.shutdown()
        return

    # Start Telethon user-bot (only if explicitly enabled and session file exists)
    session_path = f"/data/{settings.tg_session_name}.session"
    userbot_ready = (
        settings.enable_userbot
        and settings.tg_api_id
        and settings.tg_api_hash
        and __import__("os").path.exists(session_path)
    )

    if not userbot_ready:
        reason = (
            "ENABLE_USERBOT=false" if not settings.enable_userbot
            else "TG_API_ID/TG_API_HASH missing" if not (settings.tg_api_id and settings.tg_api_hash)
            else f"session file not found: {session_path}"
        )
        log.warning("userbot_skipped", reason=reason)
        global _shutdown_event
        _shutdown_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _shutdown_event.set)
        log.info("family_hq_started_no_userbot", agents=list(agents.keys()))
        await _shutdown_event.wait()
        scheduler.shutdown(wait=False)
        await bot_manager.shutdown()
        return

    userbot = UserBot(
        api_id=settings.tg_api_id,
        api_hash=settings.tg_api_hash,
        session_name=settings.tg_session_name,
        phone=settings.tg_phone,
        chat_id=chat_id,
    )

    userbot.add_message_handler(
        lambda msg: handle_new_message(
            msg, dispatcher, parser, agents, registry, access_control, memory, settings
        )
    )

    # Graceful shutdown handler
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown_event.set)

    try:
        await userbot.start()
        log.info("family_hq_started", agents=list(agents.keys()), chat_id=chat_id)
        await _shutdown_event.wait()
    finally:
        log.info("family_hq_shutting_down")
        scheduler.shutdown(wait=False)
        await userbot.stop()
        await bot_manager.shutdown()
        log.info("family_hq_stopped")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Family HQ — семейный ИИ-штаб")
    parser.add_argument("--init-db", action="store_true", help="Инициализировать БД и выйти")
    parser.add_argument("--dry-run", action="store_true", help="Симуляция без Telegram")
    parser.add_argument("--interactive", action="store_true", help="Интерактивный режим (ввод из консоли)")
    args = parser.parse_args()

    if args.init_db:
        async def init_only() -> None:
            settings = get_settings()
            setup_logging(settings.log_level)
            await init_db(settings.db_path)
            log.info("db_initialized", path=settings.db_path)

        asyncio.run(init_only())
        sys.exit(0)

    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
