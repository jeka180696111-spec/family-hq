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

        # Dispatch loop with peer-to-peer chaining (max 3 hops)
        await _dispatch_chain(
            text=text,
            sender_name=sender_name,
            dispatcher=dispatcher,
            parser=parser,
            agents=agents,
            registry=registry,
            context=context,
            chain_depth=0,
            origin_agent=None,
        )

    except Exception:
        log.exception("message_handler_error")


_MAX_CHAIN_DEPTH = 3

# Topical filters — hard rules that override the LLM dispatcher when it's too polite.
# If a message clearly belongs to one zone, agents from OTHER zones are removed
# from the task list regardless of what dispatcher decided.
_DEVOPS_KEYWORDS_RE = None  # built lazily

import re as _re

def _is_devops_topic(text: str) -> bool:
    lower = (text or "").lower()
    devops_hits = [
        "рестарт", "перезапус", "деплой", "redeploy", "коммит",
        " pr ", "pull request", "логи", "найми", "уволь",
        "проверь сервис", "перезагрузи", "перезагрузить",
    ]
    return any(k in lower for k in devops_hits)


def _is_news_topic(text: str) -> bool:
    lower = (text or "").lower()
    return any(k in lower for k in [
        "новости", "что нового", "обстановк", "тревог", "канал @",
        "добавь канал", "удали канал", "по одессе", "по украине",
        "фронт", "шахед", "ракет",
    ])


def _filter_tasks_by_topic(tasks: list, text: str) -> list:
    """Remove off-topic agents from the routing decision when topic is unambiguous."""
    if not tasks:
        return tasks
    if _is_devops_topic(text):
        return [t for t in tasks if t.agent_id == "devops"]
    if _is_news_topic(text):
        return [t for t in tasks if t.agent_id == "news"]
    return tasks


_AGENT_NAME_PATTERNS = {
    "nanny": ["няня", "няне", "няню"],
    "news": ["дозорный", "дозорному", "дозорного"],
    "calendar": ["ежедневник", "ежедневнику", "календарь"],
    "cook": ["гурман", "гурману", "гурмана"],
    "health": ["айболит", "айболиту"],
    "devops": ["прораб", "прорабу", "прораба"],
}
# Match by verb roots so different forms work (проверь/проверяй/проверим/проверишь и т.д.)
_ACTION_HINTS = [
    # restart/deploy
    "рестарт", "перезапус", "редеплой", "redeploy",
    # check/verify
    "провер", "посмотри", "глянь", "глянуть", "убедись",
    # do/make
    "сделай", "делай", "запус", "пингуй", "обнови", "поправ", "почин",
    # help/clarify
    "помоги", "уточни",
    # tool/feature requests to devops
    "нужен tool", "нужна функция", "нет инструмента", "нет функции",
    "добавь функ", "добавь tool", "реализуй", "напиши код",
    "не умею", "не могу",
    # explicit "please / need to"
    "нужно ", "надо ", "пожалуйста",
]


def _find_addressed_agent(text: str, exclude: str | None) -> str | None:
    """Detect if `text` addresses another agent by name AND contains an action verb."""
    if not text:
        return None
    lower = text.lower()
    has_action = any(hint in lower for hint in _ACTION_HINTS)
    if not has_action:
        return None
    for agent_id, names in _AGENT_NAME_PATTERNS.items():
        if agent_id == exclude:
            continue
        if any(name in lower for name in names):
            return agent_id
    return None


async def _dispatch_chain(
    text: str,
    sender_name: str,
    dispatcher: Dispatcher,
    parser: MessageParser,
    agents: dict[str, Any],
    registry: AgentRegistry,
    context: ConversationContext,
    chain_depth: int,
    origin_agent: str | None,
) -> None:
    """Dispatch a message to agents; if an agent's reply addresses another, recurse."""
    recent = await context.get_recent(8)
    result = await dispatcher.dispatch(
        message_text=text,
        sender_name=sender_name,
        active_agent_ids=registry.active_ids(),
        recent_context=recent,
    )
    parsed = await parser.parse(text)

    priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    # Hard topic filter — overrides dispatcher when topic is unambiguous (system → only devops, etc.)
    filtered = _filter_tasks_by_topic(result.tasks, text)
    sorted_tasks = sorted(filtered, key=lambda t: priority_order.get(t.priority, 99))

    for task in sorted_tasks:
        agent = agents.get(task.agent_id)
        if not agent:
            log.warning("agent_not_found", agent_id=task.agent_id)
            continue
        # Don't let an agent answer itself within the same chain
        if task.agent_id == origin_agent:
            continue

        try:
            response = await agent.handle(
                message_text=text,
                sender_name=sender_name,
                context=context,
                parsed_actions=[a.model_dump() for a in parsed.actions],
            )
        except Exception:
            log.exception("agent_handle_failed", agent_id=task.agent_id)
            continue

        # Peer-to-peer chain: if agent's reply addresses someone with an action
        if chain_depth + 1 >= _MAX_CHAIN_DEPTH:
            continue
        reply_text = getattr(response, "text", "") or ""
        addressed = _find_addressed_agent(reply_text, exclude=task.agent_id)
        if addressed and addressed in agents:
            log.info("peer_chain", from_agent=task.agent_id, to_agent=addressed, depth=chain_depth + 1)
            await _dispatch_chain(
                text=reply_text,
                sender_name=f"[{task.agent_id}]",
                dispatcher=dispatcher,
                parser=parser,
                agents=agents,
                registry=registry,
                context=context,
                chain_depth=chain_depth + 1,
                origin_agent=task.agent_id,
            )


async def run(dry_run: bool = False) -> None:
    """Main application runner."""
    global _shutdown_event
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

    railway = None
    if settings.railway_api_token and settings.railway_project_id:
        from src.integrations.railway_api import RailwayClient
        railway = RailwayClient(settings.railway_api_token, settings.railway_project_id)

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
        "cook": CookAgent(**base_args, web_search=web_search, sheets_client=sheets),
        "health": HealthAgent(**base_args),
        "devops": DevOpsAgent(**base_args, github_client=github, railway_client=railway),
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

    # Start Telethon user-bot (needs ENABLE_USERBOT=true + session string or session file)
    import os as _os
    session_path = f"/data/{settings.tg_session_name}.session"
    has_session = bool(settings.tg_session_string) or _os.path.exists(session_path)
    userbot_ready = (
        settings.enable_userbot
        and settings.tg_api_id
        and settings.tg_api_hash
        and has_session
    )

    if not userbot_ready:
        reason = (
            "ENABLE_USERBOT=false" if not settings.enable_userbot
            else "TG_API_ID/TG_API_HASH missing" if not (settings.tg_api_id and settings.tg_api_hash)
            else "no TG_SESSION_STRING and no session file"
        )
        log.warning("userbot_skipped", reason=reason)
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
        session_string=settings.tg_session_string,
    )

    userbot.add_message_handler(
        lambda msg: handle_new_message(
            msg, dispatcher, parser, agents, registry, access_control, memory, settings
        )
    )

    # News ingestion: save posts from tracked channels and detect alerts
    from src.integrations.news_ingest import NewsIngestor
    news_ingestor = NewsIngestor(memory, bot_manager=bot_manager, chat_id=chat_id)
    await news_ingestor.load_tracked_channels()
    userbot.add_news_handler(news_ingestor.handle)

    # Graceful shutdown handler
    _shutdown_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown_event.set)

    try:
        await userbot.start()
        log.info("family_hq_started", agents=list(agents.keys()), chat_id=chat_id)

        # Subscribe to tracked channels AFTER userbot is connected.
        # Throttle: Telegram floods with ~20 joins/min, sleep 4s between.
        from sqlalchemy import select, update
        from src.db.models import NewsChannel
        async with memory._engine.connect() as conn:
            channel_rows = list(await conn.execute(select(NewsChannel)))
        for ch in channel_rows:
            if not ch.username:
                continue
            try:
                resolved_id = await userbot.subscribe_to_channel(ch.username)
                if resolved_id is None:
                    # Channel doesn't exist / is private — mark inactive in DB
                    async with memory._engine.begin() as conn:
                        await conn.execute(
                            update(NewsChannel)
                            .where(NewsChannel.username == ch.username)
                            .values(active=0)
                        )
                    log.warning("channel_marked_inactive", username=ch.username)
                elif resolved_id != ch.channel_id:
                    async with memory._engine.begin() as conn:
                        await conn.execute(
                            update(NewsChannel)
                            .where(NewsChannel.username == ch.username)
                            .values(channel_id=resolved_id, active=1)
                        )
            except Exception:
                log.exception("channel_join_failed", username=ch.username)
            await asyncio.sleep(4)
        await news_ingestor.load_tracked_channels()
        log.info("news_subscriptions_done", count=len(channel_rows))

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
