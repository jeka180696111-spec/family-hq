"""Manager for 7 Telegram bots sharing a single process and event loop."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from telegram import Bot
from telegram import Message as TgMessage
from telegram.error import TelegramError
import structlog

log = structlog.get_logger()


class BotManager:
    """
    Manages 7 Telegram bots in a single process.

    Each bot is a lightweight ``telegram.Bot`` instance (send-only).
    We deliberately skip full ``Application`` setup because message
    reading is handled by the Telethon user-bot; these bots only send.
    """

    def __init__(self) -> None:
        self._bots: dict[str, Bot] = {}  # agent_id -> Bot

    async def register(self, agent_id: str, token: str) -> None:
        """Register a bot for an agent. Skip silently if token is empty."""
        if not token:
            log.warning("bot_token_missing", agent_id=agent_id)
            return

        bot = Bot(token=token)
        # Verify the token is valid before storing
        try:
            me = await bot.get_me()
            self._bots[agent_id] = bot
            log.info(
                "bot_registered",
                agent_id=agent_id,
                username=me.username,
                bot_id=me.id,
            )
        except TelegramError as exc:
            log.error(
                "bot_registration_failed",
                agent_id=agent_id,
                error=str(exc),
            )

    async def send_message(
        self,
        agent_id: str,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str = "HTML",
    ) -> TgMessage | None:
        """Send a message from the specified agent's bot."""
        bot = self._bots.get(agent_id)
        if bot is None:
            log.error("bot_not_found", agent_id=agent_id)
            return None

        try:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_message_id,
            )
            log.debug(
                "message_sent",
                agent_id=agent_id,
                chat_id=chat_id,
                message_id=message.message_id,
            )
            return message
        except TelegramError as exc:
            log.error(
                "send_message_failed",
                agent_id=agent_id,
                chat_id=chat_id,
                error=str(exc),
            )
            return None

    async def send_to_all_owners(
        self,
        agent_id: str,
        owner_ids: list[int],
        text: str,
    ) -> None:
        """Send a private message to every owner in *owner_ids*."""
        tasks = [
            self.send_message(agent_id=agent_id, chat_id=owner_id, text=text)
            for owner_id in owner_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for owner_id, result in zip(owner_ids, results):
            if isinstance(result, Exception):
                log.error(
                    "send_to_owner_failed",
                    agent_id=agent_id,
                    owner_id=owner_id,
                    error=str(result),
                )

    async def get_bot(self, agent_id: str) -> Bot | None:
        """Return the ``Bot`` object for *agent_id*, or ``None``."""
        return self._bots.get(agent_id)

    async def shutdown(self) -> None:
        """Close all bot HTTP sessions gracefully."""
        for agent_id, bot in self._bots.items():
            try:
                await bot.close()
                log.info("bot_closed", agent_id=agent_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("bot_close_error", agent_id=agent_id, error=str(exc))
        self._bots.clear()
        log.info("bot_manager_shutdown_complete")
