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

            # Держим индикатор «печатает…» пока агент думает.
            # Telegram гасит его через ~5 сек, поэтому шлём в цикле.
            stop_typing = asyncio.Event()

            async def _keep_typing():
                try:
                    while not stop_typing.is_set():
                        try:
                            await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
                        except Exception:
                            pass
                        try:
                            await asyncio.wait_for(stop_typing.wait(), timeout=4.0)
                        except asyncio.TimeoutError:
                            continue
                except Exception:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                reply = await agent.handle(text, user_name=user, chat_id=msg.chat_id)
                if reply:
                    await msg.reply_text(reply)
            except Exception as e:
                log.exception("altron_reply_failed")
                try:
                    await msg.reply_text(f"⚠️ Упал: {str(e)[:150]}")
                except Exception:
                    pass
            finally:
                stop_typing.set()
                try:
                    await typing_task
                except Exception:
                    pass

        async def _voice_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.effective_chat or update.effective_chat.id != allowed_chat:
                return
            msg = update.message
            if not msg or not (msg.voice or msg.audio):
                return
            voice = msg.voice or msg.audio
            user = msg.from_user.first_name if msg.from_user else "?"
            log.info("altron_voice_incoming", duration=voice.duration, user=user)

            stop_typing = asyncio.Event()

            async def _keep_typing():
                try:
                    while not stop_typing.is_set():
                        try:
                            await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
                        except Exception:
                            pass
                        try:
                            await asyncio.wait_for(stop_typing.wait(), timeout=4.0)
                        except asyncio.TimeoutError:
                            continue
                except Exception:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                # Скачиваем voice
                import tempfile, os as _os
                tg_file = await voice.get_file()
                fd, path = tempfile.mkstemp(suffix=".ogg")
                _os.close(fd)
                try:
                    await tg_file.download_to_drive(path)
                    # Транскрибируем через Gemini
                    gemini = getattr(agent, "_gemini", None)
                    if gemini is None or not hasattr(gemini, "transcribe_audio"):
                        await msg.reply_text("⚠️ Транскрипция голоса не настроена.")
                        return
                    transcript = await gemini.transcribe_audio(path, mime="audio/ogg")
                    transcript = (transcript or "").strip()
                    if not transcript:
                        await msg.reply_text("🤷 Не разобрал голос.")
                        return
                    log.info("altron_voice_transcribed", text=transcript[:80])
                    # Показываем что услышали и обрабатываем как обычный текст
                    await msg.reply_text(f"🎤 «{transcript}»")
                    reply = await agent.handle(transcript, user_name=user, chat_id=msg.chat_id)
                    if reply:
                        await msg.reply_text(reply)
                finally:
                    try:
                        _os.unlink(path)
                    except Exception:
                        pass
            except Exception as e:
                log.exception("altron_voice_failed")
                try:
                    await msg.reply_text(f"⚠️ С голосом упал: {str(e)[:150]}")
                except Exception:
                    pass
            finally:
                stop_typing.set()
                try:
                    await typing_task
                except Exception:
                    pass

        async def _photo_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.effective_chat or update.effective_chat.id != allowed_chat:
                return
            msg = update.message
            photos = msg.photo if msg else None
            if not photos:
                return
            user = msg.from_user.first_name if msg.from_user else "?"
            caption = (msg.caption or "").strip()
            log.info("altron_photo_incoming", user=user, caption=caption[:60])

            stop_typing = asyncio.Event()

            async def _keep_typing():
                try:
                    while not stop_typing.is_set():
                        try:
                            await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
                        except Exception:
                            pass
                        try:
                            await asyncio.wait_for(stop_typing.wait(), timeout=4.0)
                        except asyncio.TimeoutError:
                            continue
                except Exception:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                import tempfile, os as _os
                # Берём самый большой размер (последний в массиве)
                tg_file = await photos[-1].get_file()
                fd, path = tempfile.mkstemp(suffix=".jpg")
                _os.close(fd)
                try:
                    await tg_file.download_to_drive(path)
                    gemini = getattr(agent, "_gemini", None)
                    if gemini is None or not hasattr(gemini, "vision_complete"):
                        await msg.reply_text("⚠️ Vision не настроен.")
                        return
                    prompt = caption or (
                        "Опиши что на фото на русском, коротко. "
                        "Если это чек/анализ/рецепт — извлеки все цифры и названия. "
                        "Если медицинский документ — перечисли показатели."
                    )
                    system = (
                        "Ты Альтрон — семейный ассистент. Отвечай коротко, по-русски, без канцелярита. "
                        "Извлекай факты, не выдумывай."
                    )
                    reply = await gemini.vision_complete(
                        image_path=path, prompt=prompt, system=system, max_tokens=800,
                    )
                    reply = (reply or "").strip() or "Не смог разобрать фото."
                    await msg.reply_text(reply)
                finally:
                    try:
                        _os.unlink(path)
                    except Exception:
                        pass
            except Exception as e:
                log.exception("altron_photo_failed")
                try:
                    await msg.reply_text(f"⚠️ С фото упал: {str(e)[:150]}")
                except Exception:
                    pass
            finally:
                stop_typing.set()
                try:
                    await typing_task
                except Exception:
                    pass

        app = Application.builder().token(self._token).build()
        app.add_handler(CommandHandler("start", _start_cmd))
        app.add_handler(CommandHandler("ping", _ping_cmd))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_msg))
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _voice_msg))
        app.add_handler(MessageHandler(filters.PHOTO, _photo_msg))
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
