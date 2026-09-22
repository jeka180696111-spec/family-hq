"""Отдельный Telegram-бот для Альтрона.

Изолирован от bot_manager (который обслуживает 8 существующих агентов).
Слушает ТОЛЬКО ALTRON_CHAT_ID. Ни при каких условиях не отвечает
в HQ-чате или личке.

Библиотека — python-telegram-bot (та же что во всём проекте).
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

log = structlog.get_logger()


class AltronBot:
    """Стартует Application в фоне, ловит сообщения только из altron_chat_id."""

    def __init__(self, token: str, chat_id: int, agent: Any) -> None:
        self._token = token
        self._chat_id = int(chat_id)
        self._agent = agent
        self._app = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self._token or not self._chat_id:
            log.warning("altron_bot_not_configured",
                        has_token=bool(self._token), chat_id=self._chat_id)
            return
        try:
            from telegram import Update
            from telegram.constants import ChatAction
            from telegram.ext import (
                Application, MessageHandler, CommandHandler, filters, ContextTypes,
            )
        except ImportError:
            log.error("altron_ptb_missing")
            return

        allowed_chat = self._chat_id
        agent = self._agent

        async def _start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.effective_chat or update.effective_chat.id != allowed_chat:
                return
            await update.message.reply_text("👋 Альтрон подключён. Спрашивай.")

        async def _ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.effective_chat or update.effective_chat.id != allowed_chat:
                return
            await update.message.reply_text("понг")

        async def _text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # Жёстко фильтруем чат — не отвечаем в HQ-чате или личке
            if not update.effective_chat or update.effective_chat.id != allowed_chat:
                log.info("altron_msg_ignored_wrong_chat",
                         got=update.effective_chat.id if update.effective_chat else None,
                         expected=allowed_chat)
                return
            msg = update.message
            if not msg or not msg.text:
                return
            text = msg.text
            user = msg.from_user.first_name if msg.from_user else "?"
            log.info("altron_incoming", text=text[:60], user=user)
            try:
                await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
                reply = await agent.handle(text, user_name=user, chat_id=msg.chat_id)
                if reply:
                    await msg.reply_text(reply)
            except Exception as e:
                log.exception("altron_reply_failed")
                try:
                    await msg.reply_text(f"⚠️ Упал: {str(e)[:150]}")
                except Exception:
                    pass

        app = Application.builder().token(self._token).build()
        app.add_handler(CommandHandler("start", _start_cmd))
        app.add_handler(CommandHandler("ping", _ping_cmd))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_msg))
        self._app = app

        async def _run():
            try:
                log.info("altron_bot_starting", chat_id=allowed_chat)
                await app.initialize()
                await app.start()
                if app.updater:
                    await app.updater.start_polling(drop_pending_updates=True)
                # Держим таск живым пока не отменят
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                log.info("altron_bot_stopping")
            except Exception:
                log.exception("altron_bot_crashed")
            finally:
                try:
                    if app.updater and app.updater.running:
                        await app.updater.stop()
                    await app.stop()
                    await app.shutdown()
                except Exception:
                    pass

        self._task = asyncio.create_task(_run())
        log.info("altron_bot_task_created")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
