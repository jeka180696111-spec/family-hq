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

    # Dedup-window: если тот же текст в тот же чат от того же бота
    # приходит в этот интервал секунд — второй посыл дропаем.
    _DEDUP_WINDOW_SEC = 5.0

    def __init__(self) -> None:
        self._bots: dict[str, Bot] = {}  # agent_id -> Bot
        self._apps: dict[str, Any] = {}  # agent_id -> Application (for callback polling)
        # Race-condition guard: (agent, chat, hash(text)) → ts
        self._recent_sends: dict[tuple[str, int, int], float] = {}

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

    async def start_callback_polling(self, callback_fn: Callable) -> None:
        """Start a CallbackQuery polling Application for each registered bot."""
        try:
            from telegram.ext import Application, CallbackQueryHandler
        except Exception:
            log.warning("callback_polling_unavailable_no_telegram_ext")
            return

        for agent_id, bot in self._bots.items():
            try:
                app = Application.builder().bot(bot).build()

                async def _handler(update, context, _aid=agent_id):
                    cq = update.callback_query
                    if cq is None:
                        return
                    try:
                        await callback_fn(cq)
                    except Exception:
                        log.exception("callback_dispatch_failed", agent=_aid)

                app.add_handler(CallbackQueryHandler(_handler))
                await app.initialize()
                await app.start()
                await app.updater.start_polling(allowed_updates=["callback_query"])
                self._apps[agent_id] = app
                log.info("callback_polling_started", agent=agent_id)
            except Exception:
                log.exception("callback_polling_failed", agent=agent_id)

    async def send_typing(self, agent_id: str, chat_id: int) -> None:
        """Send 'typing' chat action — shows 'NyaName печатает...' to users. Lasts ~5 seconds."""
        bot = self._bots.get(agent_id)
        if bot is None:
            return
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            log.debug("send_typing_failed", agent_id=agent_id)

    async def send_message(
        self,
        agent_id: str,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
        message_thread_id: int | None = None,
    ) -> TgMessage | None:
        """Send a message from the specified agent's bot."""
        bot = self._bots.get(agent_id)
        if bot is None:
            log.error("bot_not_found", agent_id=agent_id)
            return None

        # Dedup — если такое же сообщение уже уходило в последние 5 сек
        # (race из-за double-trigger scheduler/handler), пропускаем.
        import time as _time
        now = _time.monotonic()
        key = (agent_id, chat_id, hash(text))
        last_ts = self._recent_sends.get(key)
        if last_ts is not None and (now - last_ts) < self._DEDUP_WINDOW_SEC:
            log.warning(
                "duplicate_send_suppressed",
                agent_id=agent_id, chat_id=chat_id,
                text_preview=text[:80], age_sec=round(now - last_ts, 2),
            )
            return None
        self._recent_sends[key] = now
        # Периодически чистим устаревшие ключи чтобы не расти бесконечно.
        if len(self._recent_sends) > 500:
            cutoff = now - self._DEDUP_WINDOW_SEC * 4
            self._recent_sends = {
                k: v for k, v in self._recent_sends.items() if v >= cutoff
            }

        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_to_message_id:
            kwargs["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            rows = []
            for row in reply_markup.get("inline_keyboard", []):
                rows.append([InlineKeyboardButton(text=b["text"], callback_data=b.get("callback_data", "")) for b in row])
            kwargs["reply_markup"] = InlineKeyboardMarkup(rows)
        if message_thread_id:
            kwargs["message_thread_id"] = message_thread_id

        try:
            message = await bot.send_message(**kwargs)
            log.debug(
                "message_sent",
                agent_id=agent_id,
                chat_id=chat_id,
                message_id=message.message_id,
            )
            return message
        except TelegramError as exc:
            err_str = str(exc)
            # Fallback: Telegram отверг из-за parse_mode (спецсимволы
            # < > & * _ в тексте — «Кондер >28», «**жирный**»).
            # Пробуем ещё раз в plain text — лучше некрасивое сообщение
            # чем полная тишина.
            if "can't parse entities" in err_str.lower() or "unsupported start tag" in err_str.lower():
                log.warning(
                    "send_retry_plain",
                    agent_id=agent_id, chat_id=chat_id,
                    error=err_str[:120],
                )
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("parse_mode", None)
                try:
                    message = await bot.send_message(**retry_kwargs)
                    return message
                except TelegramError as exc2:
                    log.error(
                        "send_retry_plain_failed",
                        agent_id=agent_id, chat_id=chat_id,
                        error=str(exc2)[:200],
                    )
                    return None
            log.error(
                "send_message_failed",
                agent_id=agent_id,
                chat_id=chat_id,
                error=err_str,
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

    async def send_photo(
        self,
        agent_id: str,
        chat_id: int,
        photo_bytes: bytes,
        caption: str = "",
        reply_markup: dict | None = None,
        message_thread_id: int | None = None,
    ) -> TgMessage | None:
        bot = self._bots.get(agent_id)
        if bot is None:
            return None
        import io
        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": io.BytesIO(photo_bytes),
            "caption": caption[:1024],
            "parse_mode": "HTML",
        }
        if reply_markup:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            rows = [[InlineKeyboardButton(text=b["text"], callback_data=b.get("callback_data", "")) for b in r] for r in reply_markup.get("inline_keyboard", [])]
            kwargs["reply_markup"] = InlineKeyboardMarkup(rows)
        if message_thread_id:
            kwargs["message_thread_id"] = message_thread_id
        try:
            return await bot.send_photo(**kwargs)
        except TelegramError as exc:
            log.error("send_photo_failed", agent_id=agent_id, error=str(exc))
            return None

    async def send_poll(
        self,
        agent_id: str,
        chat_id: int,
        question: str,
        options: list[str],
        is_anonymous: bool = False,
        message_thread_id: int | None = None,
    ) -> TgMessage | None:
        bot = self._bots.get(agent_id)
        if bot is None:
            return None
        try:
            kwargs: dict[str, Any] = {
                "chat_id": chat_id, "question": question[:300],
                "options": [o[:100] for o in options[:10]],
                "is_anonymous": is_anonymous,
            }
            if message_thread_id:
                kwargs["message_thread_id"] = message_thread_id
            return await bot.send_poll(**kwargs)
        except TelegramError as exc:
            log.error("send_poll_failed", agent_id=agent_id, error=str(exc))
            return None

    async def shutdown(self) -> None:
        """Close all bot HTTP sessions gracefully."""
        # Stop callback polling first
        for agent_id, app in self._apps.items():
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception:
                pass
        self._apps.clear()
        for agent_id, bot in self._bots.items():
            try:
                await bot.close()
                log.info("bot_closed", agent_id=agent_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("bot_close_error", agent_id=agent_id, error=str(exc))
        self._bots.clear()
        log.info("bot_manager_shutdown_complete")
