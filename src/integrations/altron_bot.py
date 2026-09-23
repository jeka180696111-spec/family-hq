"""Отдельный Telegram-бот для Альтрона.

Изолирован от bot_manager (который обслуживает 8 существующих агентов).
Слушает ТОЛЬКО ALTRON_CHAT_ID. Ни при каких условиях не отвечает
в HQ-чате или личке.

Библиотека — python-telegram-bot (та же что во всём проекте).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import structlog

log = structlog.get_logger()


class AltronBot:
    """Стартует Application в фоне, ловит сообщения только из altron_chat_id."""

    def __init__(self, token: str, chat_id: int, agent: Any, memory: Any = None) -> None:
        self._token = token
        self._chat_id = int(chat_id)
        self._agent = agent
        self._memory = memory
        self._app = None
        self._task: asyncio.Task | None = None
        self._alert_watch_task: asyncio.Task | None = None
        # region -> {"started_at": str, "digest_hash": str, "message_id": int|None, "last_sent_at": float}
        self._alert_state: dict[str, dict] = {}

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

        # Фоновый watcher тревог — только если memory передана
        if self._memory is not None:
            self._alert_watch_task = asyncio.create_task(self._watch_alerts())
            log.info("altron_alert_watcher_started")

    async def stop(self) -> None:
        for t in (self._alert_watch_task, self._task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except Exception:
                    pass

    # ─── Alert broadcasting ────────────────────────────────────────

    async def _watch_alerts(self) -> None:
        """Быстрый (3с) опрос ActiveAlert + фолбэк-дайджест если Штаб отстаёт.

        - Новая тревога → скелет («ТРЕВОГА · регион · с HH:MM») мгновенно.
        - Штабной digest_json готов → редактируем ту же карточку полной раскладкой.
        - Штабной digest ещё не готов, а тревога длится >20с → собираем СВОЙ
          quick-digest из последних AlertPost через Gemini и обновляем карточку.
        - Свежие AlertPost во время тревоги → тоже триггерят пересбор digest.
        - Отбой → «✅ ОТБОЙ · регион · длилось N мин».
        """
        import time
        from sqlalchemy import select
        from src.db.models import ActiveAlert, AlertPost
        from src.integrations.alert_digest import format_digest

        await asyncio.sleep(5)
        POLL_SEC = 3
        while True:
            try:
                if self._app is None or self._app.bot is None:
                    await asyncio.sleep(POLL_SEC)
                    continue
                async with self._memory._engine.connect() as conn:
                    rows = list(await conn.execute(select(ActiveAlert)))

                current = {r.region: r for r in rows}
                now_ts = time.time()

                for region, aa in current.items():
                    digest_raw = aa.digest_json or ""
                    prev = self._alert_state.get(region)
                    if not prev:
                        text = self._format_start_card(region, aa.started_at)
                        try:
                            msg = await self._app.bot.send_message(
                                chat_id=self._chat_id, text=text, parse_mode="HTML",
                            )
                            self._alert_state[region] = {
                                "started_at": aa.started_at,
                                "digest_hash": "",
                                "message_id": msg.message_id,
                                "opened_at": now_ts,
                                "own_digest_at": 0.0,
                                "last_alert_post_id": 0,
                            }
                            log.info("altron_alert_start_sent", region=region)
                        except Exception:
                            log.exception("altron_alert_start_failed", region=region)
                        continue

                    prev = self._alert_state[region]
                    # 1) Штабной digest — источник истины, если он есть
                    if digest_raw:
                        h = str(hash(digest_raw))
                        if h != prev.get("digest_hash"):
                            try:
                                digest = json.loads(digest_raw)
                                text = format_digest(digest, region, aa.started_at, sources_count=0, top_chans=None)
                                await self._app.bot.edit_message_text(
                                    chat_id=self._chat_id,
                                    message_id=prev["message_id"],
                                    text=text, parse_mode="HTML",
                                )
                                prev["digest_hash"] = h
                            except Exception:
                                log.exception("altron_alert_update_failed", region=region)
                        continue

                    # 2) Штаб не успел — сами читаем свежие AlertPost и делаем
                    #    свой quick-digest не чаще раз в 15 сек.
                    if now_ts - prev.get("own_digest_at", 0) < 15:
                        continue
                    async with self._memory._engine.connect() as conn:
                        posts = list(await conn.execute(
                            select(AlertPost)
                            .where(AlertPost.region == region)
                            .order_by(AlertPost.id.desc())
                            .limit(15)
                        ))
                    max_pid = max((p.id for p in posts), default=0)
                    if not posts or max_pid <= prev.get("last_alert_post_id", 0):
                        # Ничего нового — попробуем через 15 сек снова
                        prev["own_digest_at"] = now_ts
                        continue
                    own_text = await self._own_quick_digest(region, aa.started_at, posts)
                    if own_text:
                        try:
                            await self._app.bot.edit_message_text(
                                chat_id=self._chat_id,
                                message_id=prev["message_id"],
                                text=own_text, parse_mode="HTML",
                            )
                            prev["own_digest_at"] = now_ts
                            prev["last_alert_post_id"] = max_pid
                        except Exception:
                            log.exception("altron_own_digest_edit_failed", region=region)

                # Отбой
                for region in list(self._alert_state.keys()):
                    if region in current:
                        continue
                    st = self._alert_state[region]
                    try:
                        try:
                            started_dt = datetime.fromisoformat(st["started_at"])
                            duration_min = max(1, int((datetime.now(started_dt.tzinfo) - started_dt).total_seconds() / 60))
                        except Exception:
                            duration_min = 0
                        await self._app.bot.send_message(
                            chat_id=self._chat_id,
                            text=f"✅ <b>ОТБОЙ · {region}</b> · длилось {duration_min} мин",
                            parse_mode="HTML",
                        )
                        log.info("altron_alert_end_sent", region=region, duration_min=duration_min)
                    except Exception:
                        log.exception("altron_alert_end_failed", region=region)
                    del self._alert_state[region]
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("altron_alert_watch_loop_err")

            try:
                await asyncio.sleep(POLL_SEC)
            except asyncio.CancelledError:
                raise

    async def _own_quick_digest(self, region: str, started_at: str, posts) -> str:
        """LLM-суммаризация свежих AlertPost, когда штабной digest ещё не готов."""
        gemini = getattr(self._agent, "_gemini", None)
        if gemini is None:
            return ""
        try:
            dt = datetime.fromisoformat(started_at)
            hm = dt.strftime("%H:%M")
        except Exception:
            hm = "?"
        raw = "\n---\n".join(
            f"[{p.channel_title or p.channel_id}]: {(p.text or '')[:600]}"
            for p in reversed(posts)
        )
        system = (
            "Ты Альтрон. Собери короткую сводку по активной тревоге. "
            "Русский, HTML-теги <b> для ключевого. 5-8 строк максимум. "
            "Формат:\n"
            f"🚨 <b>ТРЕВОГА · {region}</b> · с {hm}\n"
            "✈ ЛЕТИТ: <шахед/ракета/КАБ> × N (если есть)\n"
            "🎯 КУРС: <куда/откуда> (если есть)\n"
            "💥 ПРИЛЁТЫ: <место — что> (если подтверждено)\n"
            "Если данных нет — так и напиши «пока без деталей». Не выдумывай."
        )
        try:
            text = await gemini.complete(
                system=system,
                messages=[{"role": "user", "content": raw}],
                max_tokens=400,
            )
            return (text or "").strip()
        except Exception:
            log.exception("altron_own_digest_llm_failed")
            return ""

    @staticmethod
    def _format_start_card(region: str, started_at: str) -> str:
        try:
            dt = datetime.fromisoformat(started_at)
            hm = dt.strftime("%H:%M")
        except Exception:
            hm = "?"
        return (
            f"🚨 <b>ТРЕВОГА · {region}</b> · с {hm}\n"
            + "─" * 20
            + "\n⏳ Собираю данные — что летит и куда…"
        )
