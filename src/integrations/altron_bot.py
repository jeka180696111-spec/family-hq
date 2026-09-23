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


def _dedup_channels(names: list[str | None]) -> list[str]:
    """Убрать дубли из списка каналов, сохранив порядок появления."""
    seen: set[str] = set()
    out: list[str] = []
    for n in names or []:
        if not n:
            continue
        key = str(n).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _assess_threat(
    our_region: str, targets: list, hits: list, weapons: list,
) -> tuple[str, str]:
    """Грубая оценка угрозы ИМЕННО НАМ (Одесса) на основе digest.

    Возвращает (эмодзи-индикатор, короткий вердикт).
    """
    reg_l = (our_region or "").lower()
    # Наш регион в курсе или прилётах — красный
    def _mentions_us(text: str) -> bool:
        t = (text or "").lower()
        # Одесса + область
        for kw in ("одес", "южн", "затока"):
            if kw in t:
                return True
        return False

    def _flatten(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            yield from (v for v in x.values() if isinstance(v, str))

    target_hits_us = any(_mentions_us(s) for t in (targets or []) for s in _flatten(t))
    hit_us = any(_mentions_us(str(h.get("location", ""))) or _mentions_us(str(h.get("detail", ""))) for h in (hits or []))
    strong_weapons = any(
        (w.get("type", "") or "").lower() in ("ракета", "балістична", "балистическая", "крылатая ракета", "х-101", "кинжал", "искандер")
        for w in (weapons or [])
    )

    if hit_us:
        return ("🔴", "ПРИЛЁТ у нас — в укрытие немедленно")
    if target_hits_us:
        if strong_weapons:
            return ("🔴", "Курс на Одессу, тяжёлое оружие — в укрытие")
        return ("🟠", "Курс на Одессу — в укрытие")
    if strong_weapons and (targets or hits):
        return ("🟡", "Опасно рядом, но не по нам напрямую")
    if targets or weapons or hits:
        return ("🟢", "Активность мимо, следим")
    return ("⚪", "Пока без деталей — данных мало")


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
        self._baby_watch_task: asyncio.Task | None = None
        self._grid_watch_task: asyncio.Task | None = None
        self._direct_ingest_task: asyncio.Task | None = None
        self._brief_task: asyncio.Task | None = None
        self._selfcheck_task: asyncio.Task | None = None
        # {check_name: bool prev_state_ok}  — чтобы уведомлять только на
        # переходах здоровья: broken→ok, ok→broken.
        self._selfcheck_state: dict[str, bool] = {}
        # region -> {"started_at": str, "digest_hash": str, "message_id": int|None, "last_sent_at": float}
        self._alert_state: dict[str, dict] = {}
        # Отдельный state для собственного (direct-ingest) режима.
        # region -> {"message_id": int, "opened_at": float, "last_llm_at": float,
        #           "sources": list[str], "posts": list[str]}
        self._direct_alert_state: dict[str, dict] = {}
        self._baby_last: dict = {}
        self._grid_last_on: bool | None = None

    async def start(self) -> None:
        if not self._token or not self._chat_id:
            log.warning("altron_bot_not_configured",
                        has_token=bool(self._token), chat_id=self._chat_id)
            return
        try:
            from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
            from telegram.constants import ChatAction
            from telegram.ext import (
                Application, MessageHandler, CommandHandler, filters, ContextTypes,
                CallbackQueryHandler,
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
            # Плейсхолдер для стрим-обновлений. Создаём лениво — только
            # если стрим реально стартовал (в handle решается на force_final).
            placeholder = {"msg": None, "last_text": ""}

            async def _on_partial(acc: str) -> None:
                if not acc or acc == placeholder["last_text"]:
                    return
                shown = acc if len(acc) <= 3800 else acc[-3800:]
                try:
                    if placeholder["msg"] is None:
                        placeholder["msg"] = await msg.reply_text(shown + " ▍")
                    else:
                        await placeholder["msg"].edit_text(shown + " ▍")
                    placeholder["last_text"] = acc
                except Exception:
                    pass

            try:
                reply = await agent.handle(
                    text, user_name=user, chat_id=msg.chat_id,
                    on_partial=_on_partial,
                )
                # Финальный текст — либо в плейсхолдер (edit), либо новое сообщение
                if reply:
                    if placeholder["msg"] is not None:
                        try:
                            await placeholder["msg"].edit_text(reply)
                        except Exception:
                            await msg.reply_text(reply)
                    else:
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

        async def _callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Обработать нажатие inline-кнопки. Данные кнопки — либо просто
            текст ответа (для follow-up вопросов), либо строка вида «tool:name:json»
            (для мгновенных действий типа «активируй блэкаут»)."""
            q = update.callback_query
            if not q or not q.message or q.message.chat_id != allowed_chat:
                return
            try:
                await q.answer()
            except Exception:
                pass
            data = q.data or ""
            user = q.from_user.first_name if q.from_user else "?"
            log.info("altron_callback", data=data[:60], user=user)
            # Убираем клавиатуру у исходного сообщения — чтоб не переспрашивать
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            stop_typing = asyncio.Event()

            async def _keep_typing():
                try:
                    while not stop_typing.is_set():
                        try:
                            await context.bot.send_chat_action(allowed_chat, ChatAction.TYPING)
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
                # Просто прогоняем через agent.handle как обычный текст.
                # Юзер тапнул «Да» → отправляем «Да» ассистенту.
                reply = await agent.handle(data, user_name=user, chat_id=allowed_chat)
                if reply:
                    await context.bot.send_message(chat_id=allowed_chat, text=reply)
            except Exception as e:
                log.exception("altron_callback_failed")
                try:
                    await context.bot.send_message(chat_id=allowed_chat, text=f"⚠️ Упал: {str(e)[:150]}")
                except Exception:
                    pass
            finally:
                stop_typing.set()
                try:
                    await typing_task
                except Exception:
                    pass

        app.add_handler(CallbackQueryHandler(_callback_query))
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

        # Фоновые watchers — только если memory передана
        if self._memory is not None:
            # Свой прямой сбор постов из Telegram (независимо от штабного
            # Дозорного). Первичный источник тревог.
            self._direct_ingest_task = asyncio.create_task(self._run_direct_ingest())
            self._baby_watch_task = asyncio.create_task(self._watch_baby())
            self._grid_watch_task = asyncio.create_task(self._watch_grid())
            self._brief_task = asyncio.create_task(self._run_daily_briefs())
            self._selfcheck_task = asyncio.create_task(self._run_self_check())
            log.info("altron_watchers_started")

    async def stop(self) -> None:
        for t in (
            self._grid_watch_task, self._baby_watch_task,
            self._alert_watch_task, self._direct_ingest_task,
            self._brief_task, self._selfcheck_task,
            self._task,
        ):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except Exception:
                    pass

    async def _send(
        self, text: str, parse_mode: str = "HTML", silent: bool = False,
    ) -> None:
        """Отправить сообщение в чат Альтрона.

        silent=True — доставка без звука (для сводок, брифов, отбоя,
        восстановления сервисов).
        silent=False (default) — со звуком (важные уведомления).
        """
        if not self._app or not self._app.bot:
            return
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id, text=text, parse_mode=parse_mode,
                disable_notification=silent,
            )
        except Exception:
            log.exception("altron_bot_send_failed")

    async def send_with_buttons(
        self, text: str, options: list[str], silent: bool = False,
    ) -> None:
        """Отправить сообщение с inline-кнопками. Callback data = сам текст
        варианта (юзер тапает — эта же строка уходит агенту как ответ)."""
        if not self._app or not self._app.bot or not options:
            return
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            # 3 в ряд для коротких, 1 в ряд для длинных
            rows: list[list] = []
            for opt in options[:6]:
                # callback_data ограничен 64 байтами — режем
                cd = opt[:60]
                btn = InlineKeyboardButton(text=opt[:32], callback_data=cd)
                if len(opt) > 15:
                    rows.append([btn])
                else:
                    if rows and len(rows[-1]) < 3 and all(len(str(b.text)) <= 15 for b in rows[-1]):
                        rows[-1].append(btn)
                    else:
                        rows.append([btn])
            markup = InlineKeyboardMarkup(rows)
            await self._app.bot.send_message(
                chat_id=self._chat_id, text=text, parse_mode="HTML",
                reply_markup=markup, disable_notification=silent,
            )
        except Exception:
            log.exception("altron_send_buttons_failed")

    async def _send_voice(self, spoken_text: str, caption: str = "") -> None:
        """Голосовое сообщение мужским голосом через Microsoft Edge TTS.
        Вызывается ТОЛЬКО из tool speak_reply (по явной просьбе юзера).
        Тихо падает если edge-tts не установлен или сеть недоступна."""
        if not self._app or not self._app.bot:
            return
        if not spoken_text or not spoken_text.strip():
            return
        try:
            import edge_tts
        except ImportError:
            log.debug("altron_tts_edge_not_installed")
            return
        try:
            import tempfile, os as _os
            fd, path = tempfile.mkstemp(suffix=".mp3")
            _os.close(fd)
            # ru-RU-DmitryNeural — мужской российский голос
            communicate = edge_tts.Communicate(spoken_text[:800], "ru-RU-DmitryNeural")
            await communicate.save(path)
            try:
                with open(path, "rb") as f:
                    await self._app.bot.send_voice(
                        chat_id=self._chat_id, voice=f, caption=caption[:200] or None,
                    )
            finally:
                try:
                    _os.unlink(path)
                except Exception:
                    pass
        except Exception:
            log.exception("altron_tts_send_failed")

    # ─── Direct ingest (свой сбор постов) ─────────────────────────

    async def _run_direct_ingest(self) -> None:
        """Запуск AltronDirectIngestor с колбэками на текущий бот."""
        from src.integrations.altron_ingest import AltronDirectIngestor

        ing = AltronDirectIngestor(
            memory=self._memory,
            on_alert_start=self._direct_on_start,
            on_alert_update=self._direct_on_update,
            on_alert_clear=self._direct_on_clear,
        )
        try:
            await ing.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("altron_direct_ingest_crashed")

    async def _direct_on_start(self, region: str, post: dict, sources: list[str]) -> None:
        """Callback: пришёл первый alert-пост. Отправляем карточку."""
        import time
        try:
            started_at = post["ts"].astimezone().isoformat()
        except Exception:
            started_at = datetime.now().astimezone().isoformat()
        text = self._format_start_card(region, started_at)
        try:
            msg = await self._app.bot.send_message(
                chat_id=self._chat_id, text=text, parse_mode="HTML",
            )
        except Exception:
            log.exception("altron_direct_start_send_failed")
            return
        self._direct_alert_state[region] = {
            "message_id": msg.message_id,
            "started_at": started_at,
            "opened_at": time.time(),
            "last_llm_at": 0.0,
            "sources": list(sources),
            "posts": [post["text"]],
        }
        log.info("altron_direct_alert_start", region=region, sources=sources)

    async def _direct_on_update(self, region: str, new_posts: list, sources: list[str]) -> None:
        """Callback: обновление во время активной тревоги. Пересобираем digest
        не чаще раз в 20 сек."""
        import time
        st = self._direct_alert_state.get(region)
        if not st:
            return
        st["sources"] = list(sources)
        for p in new_posts:
            st["posts"].append(p["text"])
        st["posts"] = st["posts"][-30:]

        if time.time() - st.get("last_llm_at", 0) < 20:
            return

        card = await self._direct_build_card(region, st)
        if not card:
            return
        try:
            await self._app.bot.edit_message_text(
                chat_id=self._chat_id, message_id=st["message_id"],
                text=card, parse_mode="HTML",
            )
            st["last_llm_at"] = time.time()
        except Exception:
            log.exception("altron_direct_update_edit_failed", region=region)

    async def _direct_on_clear(self, region: str, sources: list[str]) -> None:
        """Callback: пришёл отбой."""
        st = self._direct_alert_state.get(region)
        try:
            try:
                started_dt = datetime.fromisoformat(st["started_at"]) if st else datetime.now()
                duration_min = max(1, int((datetime.now(started_dt.tzinfo) - started_dt).total_seconds() / 60))
            except Exception:
                duration_min = 0
            text = self._format_altron_endcard(
                region, st.get("started_at", "") if st else "",
                duration_min,
                digest={},  # LLM-собранные факты можно добавить позже
                sources=sources,
            )
            await self._app.bot.send_message(
                chat_id=self._chat_id, text=text, parse_mode="HTML",
                disable_notification=True,  # отбой — silent, спокойная новость
            )
            log.info("altron_direct_alert_end", region=region, duration_min=duration_min)
        except Exception:
            log.exception("altron_direct_clear_send_failed")
        self._direct_alert_state.pop(region, None)

    async def _direct_build_card(self, region: str, st: dict) -> str:
        """LLM-суммаризация накопленных постов в формат карточки Альтрона."""
        gemini = getattr(self._agent, "_gemini", None)
        if gemini is None:
            return ""
        try:
            dt = datetime.fromisoformat(st["started_at"])
            hm = dt.strftime("%H:%M")
        except Exception:
            hm = "?"
        raw = "\n---\n".join(st.get("posts") or [])
        sources = st.get("sources") or []
        src_line = ", ".join(sources[:6]) if sources else "—"
        system = (
            "Ты Альтрон. Собираешь сводку по активной воздушной тревоге в Одессе "
            "напрямую из Telegram-каналов (без штабного дозорного). "
            "Русский, HTML-теги <b>. Строго этот формат:\n\n"
            f"🚨 <b>АЛЬТРОН · ТРЕВОГА</b>\n"
            f"📍 {region} · с {hm}\n"
            + ("━" * 18) + "\n\n"
            "🟠 <b>ОЦЕНКА:</b> <короткая оценка угрозы Одессе — если есть курс "
            "или прилёты у нас, ставь 🔴 «В укрытие»; если летит мимо, 🟢 «Мимо, "
            "следим»; данных мало — ⚪>\n\n"
            "✈ <b>ЧТО ЛЕТИТ:</b> <шахед × N / крылатая ракета / КАБ / БПЛА — "
            "только если реально упомянуто>\n"
            "🎯 <b>КУРС:</b> <куда идёт — только если упомянуто>\n"
            "💥 <b>ПРИЛЁТЫ:</b> <место — что; помечай (не подтв.) если неясно>\n\n"
            + ("━" * 18) + "\n"
            f"📡 <b>Источники:</b> {src_line}\n\n"
            "Правила: не выдумывай, пропускай пустые секции. Максимум ~15 строк."
        )
        try:
            text = await gemini.complete(
                system=system,
                messages=[{"role": "user", "content": raw}],
                max_tokens=500,
            )
            return (text or "").strip()
        except Exception:
            log.exception("altron_direct_llm_card_failed")
            return ""

    # ─── Alert broadcasting (fallback via HQ Дозорный — deprecated) ─

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
                    # 1) Штабной digest — источник истины, если он есть.
                    #    Показываем в СВОЁМ формате Альтрона (не в штабном).
                    if digest_raw:
                        h = str(hash(digest_raw))
                        if h != prev.get("digest_hash"):
                            try:
                                digest = json.loads(digest_raw)
                                # Собираем список источников из AlertPost
                                async with self._memory._engine.connect() as c2:
                                    src_rows = list(await c2.execute(
                                        select(AlertPost.channel_title)
                                        .where(AlertPost.region == region)
                                        .order_by(AlertPost.id.desc())
                                        .limit(30)
                                    ))
                                sources = _dedup_channels([r[0] for r in src_rows])
                                text = self._format_altron_card(
                                    digest, region, aa.started_at, sources,
                                )
                                await self._app.bot.edit_message_text(
                                    chat_id=self._chat_id,
                                    message_id=prev["message_id"],
                                    text=text, parse_mode="HTML",
                                )
                                prev["digest_hash"] = h
                                prev["last_digest"] = digest
                                prev["last_sources"] = sources
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
                        text = self._format_altron_endcard(
                            region, st.get("started_at", ""),
                            duration_min,
                            digest=st.get("last_digest") or {},
                            sources=st.get("last_sources") or [],
                        )
                        await self._app.bot.send_message(
                            chat_id=self._chat_id, text=text, parse_mode="HTML",
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
        sources = _dedup_channels([p.channel_title for p in posts])[:6]
        src_line = ", ".join(sources) if sources else "—"
        system = (
            "Ты Альтрон. Собери короткую сводку по активной тревоге для семьи "
            "в Одессе. Русский, HTML-теги <b>. Ровно этот формат, ничего лишнего:\n\n"
            f"🚨 <b>АЛЬТРОН · ТРЕВОГА</b>\n"
            f"📍 {region} · с {hm}\n"
            + ("━" * 18) + "\n\n"
            "🟠 <b>ОЦЕНКА:</b> <строка о том, есть ли реальная угроза Одессе — если "
            "курс на нас или прилёты у нас, ставь 🔴 «В укрытие»; если летит мимо, "
            "🟢 «Активность мимо, следим»; если ничего непонятно — ⚪ «Данных мало»>\n\n"
            "✈ <b>ЧТО ЛЕТИТ:</b> <шахед × N / крылатая ракета / КАБ / БПЛА — только "
            "если реально упомянуто в постах>\n"
            "🎯 <b>КУРС:</b> <куда идёт — только если упомянуто>\n"
            "💥 <b>ПРИЛЁТЫ:</b> <место — что; помечай (не подтв.) если не confirmed>\n\n"
            + ("━" * 18) + "\n"
            f"📡 <b>Источники:</b> {src_line}\n\n"
            "Правила:\n"
            "- Если по какой-то секции данных нет — не выдумывай, пропускай её.\n"
            "- Если постов вообще мало и непонятно — оценка ⚪ и одна строка «пока "
            "без деталей».\n"
            "- Максимум ~15 строк. Не пиши ничего кроме карточки."
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

    # ─── Baby sleep watcher ────────────────────────────────────────

    async def _watch_baby(self) -> None:
        """Опрос BabyState раз в 60с. Реагирует на переходы:
        - Уснул → предложить приглушить свет.
        - Проснулся ДО 7:00 → сам включить сцену «Спальня ночь» + известить.
        - Проснулся в обычное время (7-22) → просто известить.

        Если переход был только что записан САМИМ Альтроном по команде
        пользователя (self._agent._recent_baby_transition), уведомление
        пропускаем — юзер уже в курсе.
        """
        import time
        from sqlalchemy import select
        from src.db.models import BabyState
        from datetime import datetime as _dt

        SUPPRESS_WINDOW_SEC = 180

        def _time_of(iso_ts: str | None) -> str:
            if not iso_ts:
                return _dt.now().strftime("%H:%M")
            try:
                return _dt.fromisoformat(iso_ts).strftime("%H:%M")
            except Exception:
                return _dt.now().strftime("%H:%M")

        await asyncio.sleep(20)
        while True:
            try:
                async with self._memory._engine.connect() as conn:
                    st = (await conn.execute(select(BabyState))).first()
                if st is not None:
                    curr = {
                        "sleeping_since": st.sleeping_since,
                        "awake_since": st.awake_since,
                    }
                    prev = self._baby_last
                    recent = getattr(self._agent, "_recent_baby_transition", {}) or {}
                    now_ts = time.time()

                    if prev:
                        # Заснул — silent, инфо
                        if curr["sleeping_since"] and curr["sleeping_since"] != prev.get("sleeping_since"):
                            if now_ts - recent.get("asleep", 0) > SUPPRESS_WINDOW_SEC:
                                await self._send(
                                    f"😴 <b>Матвей уснул в {_time_of(curr['sleeping_since'])}.</b>\n"
                                    "Свет в детской теперь не нужен. Скажи «выключи свет в детской» — сделаю.",
                                    silent=True,
                                )
                        # Проснулся
                        if curr["awake_since"] and curr["awake_since"] != prev.get("awake_since"):
                            from src.utils.time import now_kyiv
                            wake_hm = _time_of(curr["awake_since"])
                            hour = now_kyiv().hour
                            # Ночное пробуждение — silent (не будим уснувших взрослых)
                            if hour < 7:
                                ok = await self._try_run_scene(
                                    ["Спальня ночь", "Детская ночь", "Ночник"]
                                )
                                if now_ts - recent.get("awake", 0) > SUPPRESS_WINDOW_SEC:
                                    if ok:
                                        await self._send(
                                            f"🌙 <b>Матвей проснулся в {wake_hm}</b>\nВключил ночник ({ok}).",
                                            silent=True,
                                        )
                                    else:
                                        await self._send(
                                            f"🌙 <b>Матвей проснулся в {wake_hm}</b>\n"
                                            "Хотел включить ночник, но сцены «Спальня ночь» не нашёл.",
                                            silent=True,
                                        )
                                elif ok:
                                    await self._send(f"🌙 Заодно включил ночник ({ok}).", silent=True)
                            else:
                                if now_ts - recent.get("awake", 0) > SUPPRESS_WINDOW_SEC:
                                    await self._send(f"👶 <b>Матвей проснулся в {wake_hm}</b>", silent=True)
                    self._baby_last = curr
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("altron_baby_watch_err")
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

    async def _try_run_scene(self, candidates: list[str]) -> str | None:
        """Дёрнуть Tuya-сцену. Возвращает имя запущенной сцены или None."""
        try:
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(get_settings())
            if not tuya:
                return None
            for q in candidates:
                sc = await tuya.find_scene(q)
                if sc and not sc.get("ambiguous"):
                    await tuya.run_scene(sc.get("id"))
                    return sc.get("name")
        except Exception:
            log.exception("altron_try_scene_failed")
        return None

    # ─── Grid (electricity) watcher ────────────────────────────────

    async def _watch_grid(self) -> None:
        """Опрос инвертора. Логика скопирована из штабного grid_watcher —
        то что уже проверено на этих же скачках напряжения:

        1) PRIMARY — LuxCloud event log (recent_events). Инвертор сам
           пишет «Grid Lost / Grid Restored» / W016 / W017. Это тот же
           источник что SMS от инвертора — очень надёжно, никакой
           путаницы со скачками.
        2) FALLBACK — если events endpoint пустой, смотрим:
           - battery_charge_w > 100 → сеть есть.
           - battery_discharge_w > 50 и battery_charge_w < 5 подряд 3
             тика (90с) → сеть пропала.
           grid_import_w НЕ используем — он гуляет от скачков.
        3) Антифлаппинг: закрыть outage можно быстро, но открывать
           только с подтверждением (3 тика).
        """
        from src.config import get_settings
        from src.integrations.luxcloud import LuxCloudClient
        import time

        POLL_SEC = 30
        NEED_STABLE_OFF = 3    # 3 тика × 30с = 90с прежде чем сказать «нет света»
        COOLDOWN_SEC = 300     # 5 мин после транзиции — обратный сигнал игнор

        discharge_streak = 0
        last_transition_ts = 0.0
        last_event_time: str | None = None
        lux = None

        await asyncio.sleep(30)
        while True:
            try:
                if lux is None:
                    lux = LuxCloudClient.from_settings(get_settings())
                if lux is None:
                    await asyncio.sleep(300)
                    continue

                data = await lux.runtime()
                events = []
                try:
                    events = await lux.recent_events(hours=2)
                except Exception:
                    events = []

                battery_pct = data.get("battery_pct", 0) or 0
                try:
                    battery_charge_w = float(data.get("battery_charge_w") or 0)
                except (TypeError, ValueError):
                    battery_charge_w = 0.0
                try:
                    battery_discharge_w = float(data.get("battery_discharge_w") or 0)
                except (TypeError, ValueError):
                    battery_discharge_w = 0.0
                raw = data.get("raw", {}) or {}
                status_now = str(data.get("status") or raw.get("status") or "").lower()
                has_grid_loss_alarm = any(
                    code in status_now for code in ("w016", "w017", "f016", "f017")
                )

                now_ts = time.time()
                in_cooldown = (now_ts - last_transition_ts) < COOLDOWN_SEC

                # 1) EVENT LOG — источник истины
                event_state, event_time = self._grid_state_from_events(events, last_event_time)
                if event_time:
                    last_event_time = event_time

                if event_state is True and self._grid_last_on is not True and not in_cooldown:
                    if self._grid_last_on is False:
                        await self._send(
                            f"✅ <b>СВЕТ ДАЛИ.</b> Идёт зарядка батареи ({battery_pct}%).",
                            silent=True,
                        )
                    self._grid_last_on = True
                    last_transition_ts = now_ts
                    discharge_streak = 0
                elif event_state is False and self._grid_last_on is not False and not in_cooldown:
                    if self._grid_last_on is True:
                        await self._send(
                            "⚡ <b>СВЕТ ВЫРУБИЛИ.</b> Питание с батареи.\n"
                            f"🔋 Заряд: <b>{battery_pct}%</b> · нагрузка: "
                            f"{data.get('home_consumption_w', 0)} Вт\n\n"
                            "Совет: выключи бойлер, ТВ, зарядки. Скажи "
                            "«активируй блэкаут» — сам выключу лишнее."
                        )
                    self._grid_last_on = False
                    last_transition_ts = now_ts
                    discharge_streak = 0
                else:
                    # 2) FALLBACK — только если events молчат
                    if self._grid_last_on is None:
                        # прайминг — считаем ток есть если батарея заряжается
                        self._grid_last_on = battery_charge_w > 30 and not has_grid_loss_alarm
                    elif self._grid_last_on is True:
                        # ловим OFF: нагрузка идёт с батареи, ничего не заряжает
                        off_signal = has_grid_loss_alarm or (
                            battery_discharge_w > 50 and battery_charge_w < 5
                        )
                        if off_signal:
                            discharge_streak += 1
                            if discharge_streak >= NEED_STABLE_OFF and not in_cooldown:
                                await self._send(
                                    "⚡ <b>СВЕТ ВЫРУБИЛИ.</b> Питание с батареи.\n"
                                    f"🔋 Заряд: <b>{battery_pct}%</b> · нагрузка: "
                                    f"{data.get('home_consumption_w', 0)} Вт\n\n"
                                    "Совет: выключи бойлер, ТВ, зарядки. Скажи "
                                    "«активируй блэкаут» — сам выключу лишнее."
                                )
                                self._grid_last_on = False
                                last_transition_ts = now_ts
                                discharge_streak = 0
                        else:
                            discharge_streak = 0
                    else:  # self._grid_last_on is False
                        # ловим ON: заряд восстановился ИЛИ статус normal + слабый заряд
                        back = (
                            battery_charge_w > 100
                            or (status_now == "normal" and battery_charge_w > 30)
                        )
                        if back and not in_cooldown:
                            await self._send(
                                f"✅ <b>СВЕТ ДАЛИ.</b> Идёт зарядка батареи ({battery_pct}%).",
                                silent=True,
                            )
                            self._grid_last_on = True
                            last_transition_ts = now_ts
                            discharge_streak = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("altron_grid_watch_err")
            try:
                await asyncio.sleep(POLL_SEC)
            except asyncio.CancelledError:
                raise

    @staticmethod
    def _grid_state_from_events(
        events: list[dict], last_event_time: str | None,
    ) -> tuple[bool | None, str | None]:
        """Разбор LuxCloud event log — та же логика что в HQ grid_watcher.
        Возвращает (True/False/None, время события) — состояние сети из
        самого свежего relevant-события, None если ничего нового."""
        LOSS_KW = (
            "grid lost", "grid loss", "ac loss", "grid disconnect", "off grid",
            "off-grid", "no ac", "no grid", "grid down", "grid fault", "utility loss",
            "пропала", "нет сети", "нет подключения", "сеть пропала",
            "нет напряжения", "отключение сети", "нет переменного тока",
            "сеть отсутствует",
            "відсутн", "немає мережі", "немає підключення",
            "мережа відсутня", "відключення мережі",
            "w016", "w017", "f016", "f017",
        )
        OK_KW = (
            "grid connect", "grid restore", "grid restored", "ac connect", "ac connected",
            "grid ok", "grid available", "power on", "on grid", "on-grid", "recovered",
            "восстанов", "сеть восстановлена", "напряжение восстановлено",
            "сеть появилась", "появилось напряжение",
            "поновлен", "мережа відновлена", "мережа з'явилась",
        )
        for ev in events:
            blob = " ".join(str(v).lower() for v in (
                ev.get("name") or "", ev.get("type") or "",
                ev.get("code") or "", ev.get("status") or "",
            ))
            raw_status = str((ev.get("raw") or {}).get("status", "")).lower()
            full = f"{blob} {raw_status}"
            ev_time = ev.get("time")
            if any(kw in full for kw in LOSS_KW):
                if "recovered" in full or "восстанов" in full:
                    if ev_time and ev_time == last_event_time:
                        return None, ev_time
                    return True, ev_time
                if ev_time and ev_time == last_event_time:
                    return None, ev_time
                return False, ev_time
            if any(kw in full for kw in OK_KW):
                if ev_time and ev_time == last_event_time:
                    return None, ev_time
                return True, ev_time
        return None, last_event_time

    # ─── Self-check (Sheets / Tuya / Gemini) ─────────────────────

    async def _run_self_check(self) -> None:
        """Раз в час проверяем ключевые интеграции. Шлём уведомление
        ТОЛЬКО на переходах — раз объявили что Sheets упал, не спамим
        каждый час пока не поправят. И наоборот: как только починили,
        одно «✅ восстановлено» и молчок."""
        CHECK_INTERVAL_SEC = 3600  # 1 час
        await asyncio.sleep(120)  # первые 2 мин после старта — молчим
        while True:
            try:
                results = await self._check_all()
                for name, (ok, detail) in results.items():
                    prev = self._selfcheck_state.get(name)
                    if prev is None:
                        self._selfcheck_state[name] = ok
                        continue
                    if prev and not ok:
                        await self._send(
                            f"⚠️ <b>SELF-CHECK: {name} упал</b>\n{detail}"
                        )
                    elif (not prev) and ok:
                        await self._send(
                            f"✅ <b>SELF-CHECK: {name} восстановлен</b>",
                            silent=True,
                        )
                    self._selfcheck_state[name] = ok
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("altron_self_check_loop_err")
            try:
                await asyncio.sleep(CHECK_INTERVAL_SEC)
            except asyncio.CancelledError:
                raise

    async def _check_all(self) -> dict[str, tuple[bool, str]]:
        """Все проверки параллельно, каждая max ~5 сек."""
        results: dict[str, tuple[bool, str]] = {}
        checks = [
            ("Google Sheets", self._check_sheets()),
            ("Tuya", self._check_tuya()),
            ("Gemini", self._check_gemini()),
            ("Инвертор", self._check_inverter()),
        ]
        outcomes = await asyncio.gather(*(c for _, c in checks), return_exceptions=True)
        for (name, _), r in zip(checks, outcomes):
            if isinstance(r, Exception):
                results[name] = (False, f"{type(r).__name__}: {str(r)[:120]}")
            else:
                results[name] = r
        return results

    async def _check_sheets(self) -> tuple[bool, str]:
        try:
            from src.config import get_settings
            settings = get_settings()
            sa = getattr(settings, "google_service_account_json", "")
            sheet_id = getattr(settings, "sheet_baby_id", "")
            if not sa or not sheet_id:
                return (True, "не настроено — пропускаем")
            from src.integrations.sheets import SheetsClient
            sc = SheetsClient(sa, sheet_id, "")
            # get_worksheet_titles легковесно
            await sc._ensure_client()
            return (True, "ok")
        except Exception as e:
            return (False, str(e)[:150])

    async def _check_tuya(self) -> tuple[bool, str]:
        try:
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            tuya = TuyaClient.from_settings(get_settings())
            if tuya is None:
                return (True, "не настроено — пропускаем")
            devices = await tuya.list_devices()
            return (True, f"{len(devices)} устройств")
        except Exception as e:
            return (False, str(e)[:150])

    async def _check_gemini(self) -> tuple[bool, str]:
        gemini = getattr(self._agent, "_gemini", None)
        if gemini is None:
            return (True, "не настроено — пропускаем")
        try:
            reply = await gemini.complete(
                system="Ты Альтрон. Верни ровно строку 'ok'.",
                messages=[{"role": "user", "content": "self-check"}],
                max_tokens=8,
            )
            return (True, (reply or "").strip()[:40])
        except Exception as e:
            return (False, str(e)[:150])

    async def _check_inverter(self) -> tuple[bool, str]:
        try:
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            lux = LuxCloudClient.from_settings(get_settings())
            if lux is None:
                return (True, "не настроено — пропускаем")
            state = await lux.runtime()
            soc = state.get("battery_pct")
            return (True, f"SOC {soc}%" if soc is not None else "ok")
        except Exception as e:
            return (False, str(e)[:150])

    # ─── Daily briefs (утро / вечер) ─────────────────────────────

    async def _run_daily_briefs(self) -> None:
        """Ждём до ближайшего 8:00 или 22:00 Kyiv, шлём брифинг, спим до
        следующего слота. Пропущенные из-за рестарта не догоняем — только
        будущие."""
        from datetime import timedelta
        from src.utils.time import now_kyiv

        def _next_slot() -> tuple[datetime, str]:
            now = now_kyiv()
            morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
            evening = now.replace(hour=22, minute=0, second=0, microsecond=0)
            candidates = []
            if morning > now:
                candidates.append((morning, "morning"))
            if evening > now:
                candidates.append((evening, "evening"))
            # Воскресенье 20:00 — недельный дайджест (0=Пн, 6=Вс)
            weekly = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if now.weekday() == 6 and weekly > now:
                candidates.append((weekly, "weekly"))
            elif now.weekday() != 6:
                # Ближайшее воскресенье
                days_to_sun = (6 - now.weekday()) % 7 or 7
                candidates.append((weekly + timedelta(days=days_to_sun), "weekly"))
            if not candidates:
                candidates.append((morning + timedelta(days=1), "morning"))
            candidates.sort(key=lambda x: x[0])
            return candidates[0]

        while True:
            try:
                target, kind = _next_slot()
                wait_sec = max(1, (target - now_kyiv()).total_seconds())
                log.info("altron_next_brief", kind=kind, wait_sec=int(wait_sec))
                await asyncio.sleep(wait_sec)
                if kind == "morning":
                    text = await self._build_morning_brief()
                elif kind == "weekly":
                    text = await self._build_weekly_brief()
                else:
                    text = await self._build_evening_brief()
                if text:
                    await self._send(text, silent=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("altron_brief_loop_err")
                await asyncio.sleep(300)

    async def _build_morning_brief(self) -> str:
        """Утренний брифинг: погода, календарь, ночная тревога, состояние
        Матвея, инвертор, задачи."""
        try:
            weather = await self._agent._tool_time_weather()
        except Exception:
            weather = {}
        try:
            baby = await self._agent._tool_baby_state()
        except Exception:
            baby = {}
        try:
            cal = await self._agent._tool_calendar()
        except Exception:
            cal = {}
        try:
            inv = await self._agent._tool_inverter()
        except Exception:
            inv = {}
        try:
            shopping = await self._agent._tool_get_shopping_list()
        except Exception:
            shopping = {}

        from src.utils.time import now_kyiv
        now = now_kyiv()
        lines = [f"🌅 <b>ДОБРОЕ УТРО · {now.strftime('%A, %d.%m').capitalize()}</b>"]
        lines.append("━" * 18)

        w_temp = weather.get("temp_c") if isinstance(weather, dict) else None
        w_desc = weather.get("description", "") if isinstance(weather, dict) else ""
        w_feel = weather.get("feels_like_c") if isinstance(weather, dict) else None
        if w_temp is not None:
            row = f"🌤 <b>Погода:</b> {w_temp}°"
            if w_feel is not None and abs((w_feel or 0) - (w_temp or 0)) > 1:
                row += f" (ощущ. {w_feel}°)"
            if w_desc:
                row += f" · {w_desc}"
            lines.append(row)

        headline = baby.get("headline") if isinstance(baby, dict) else None
        if headline:
            lines.append(f"👶 <b>Матвей:</b> {headline}")

        events = (cal or {}).get("events") or []
        if events:
            lines.append("")
            lines.append("📅 <b>На сегодня:</b>")
            for e in events[:4]:
                start = e.get("start", "?")
                title = e.get("title", "?")
                lines.append(f"• {start} — {title}")
        else:
            lines.append("📅 <b>Календарь пуст.</b>")

        soc = inv.get("soc_pct") if isinstance(inv, dict) else None
        on_grid = inv.get("on_grid") if isinstance(inv, dict) else None
        if soc is not None:
            grid = "сеть есть" if on_grid else "на батарее"
            lines.append(f"🔋 <b>Инвертор:</b> {soc}% · {grid}")

        sh_items = (shopping or {}).get("items") or []
        if sh_items:
            names = [s.get("item", "?") for s in sh_items[:5]]
            more = f" +{len(sh_items) - 5}" if len(sh_items) > 5 else ""
            lines.append(f"🛒 <b>В списке:</b> {', '.join(names)}{more}")

        lines.append("")
        lines.append("<i>Задавай вопросы — я рядом.</i>")
        return "\n".join(lines)

    async def _build_evening_brief(self) -> str:
        """Вечерний итог: события Матвея за день, календарь завтра, тревоги."""
        try:
            diary = await self._agent._tool_get_baby_diary(days=1, kind="all")
        except Exception:
            diary = {}
        try:
            cal = await self._agent._tool_calendar()
        except Exception:
            cal = {}
        try:
            inv = await self._agent._tool_inverter()
        except Exception:
            inv = {}

        from src.utils.time import now_kyiv
        from datetime import timedelta
        now = now_kyiv()
        tomorrow = now + timedelta(days=1)
        lines = [f"🌙 <b>ИТОГ ДНЯ · {now.strftime('%d.%m')}</b>"]
        lines.append("━" * 18)

        events_today = (diary or {}).get("events") or []
        if events_today:
            by_kind: dict[str, int] = {}
            for ev in events_today:
                k = str(ev.get("kind", "note")).lower()
                by_kind[k] = by_kind.get(k, 0) + 1
            summary_bits = []
            if by_kind.get("food"):
                summary_bits.append(f"кормлений {by_kind['food']}")
            if by_kind.get("sleep"):
                summary_bits.append(f"снов {by_kind['sleep']}")
            if by_kind.get("diaper"):
                summary_bits.append(f"подгузников {by_kind['diaper']}")
            if by_kind.get("symptom"):
                summary_bits.append(f"симптомов {by_kind['symptom']}")
            lines.append("👶 <b>Матвей:</b> " + ", ".join(summary_bits) if summary_bits else "👶 <b>Матвей:</b> —")
        else:
            lines.append("👶 <b>Матвей:</b> в дневнике сегодня пусто")

        # События завтра
        events = (cal or {}).get("events") or []
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        tomorrow_events = [e for e in events if str(e.get("start", "")).startswith(tomorrow_str)]
        if tomorrow_events:
            lines.append("")
            lines.append("📅 <b>Завтра:</b>")
            for e in tomorrow_events[:4]:
                lines.append(f"• {e.get('start','?')[11:16]} — {e.get('title','?')}")

        soc = inv.get("soc_pct") if isinstance(inv, dict) else None
        if soc is not None:
            lines.append(f"🔋 <b>Батарея на ночь:</b> {soc}%")

        lines.append("")
        lines.append("<i>Спокойной ночи. Я слежу.</i>")
        return "\n".join(lines)

    async def _build_weekly_brief(self) -> str:
        """Воскресный дайджест: инсайты за неделю через LLM над структурой."""
        try:
            insights = await self._agent._tool_get_weekly_insights(days=7)
        except Exception:
            insights = {}
        gemini = getattr(self._agent, "_gemini", None)
        if gemini is None or not isinstance(insights, dict) or insights.get("error"):
            # Фолбэк: рендерим числа без LLM
            m = insights.get("matvey", {}) if isinstance(insights, dict) else {}
            eug = insights.get("eugene_sleep", {}) if isinstance(insights, dict) else {}
            mar = insights.get("marina_sleep", {}) if isinstance(insights, dict) else {}
            fuel = insights.get("fuel", {}) if isinstance(insights, dict) else {}
            lines = ["📊 <b>НЕДЕЛЯ · ИТОГИ</b>", "━" * 18]
            if m:
                lines.append(f"👶 Матвей: {m.get('total_events', 0)} записей, "
                             f"пробуждений {m.get('wake_ups', 0)}")
            if eug:
                lines.append(f"🌙 Евгений: спит в среднем {eug.get('avg_hours') or '—'}ч, "
                             f"ночей записано {eug.get('nights_recorded') or 0}")
            if mar:
                lines.append(f"🌙 Марина: спит в среднем {mar.get('avg_hours') or '—'}ч, "
                             f"ночей записано {mar.get('nights_recorded') or 0}")
            if fuel and fuel.get("refuels"):
                lines.append(f"⛽ Топливо: {fuel.get('refuels')} заправок, "
                             f"{fuel.get('total_liters')}л на {fuel.get('total_uah')}грн")
            return "\n".join(lines)

        import json as _json
        system = (
            "Ты Альтрон. Собери короткий недельный отчёт для семьи по числам ниже. "
            "Русский, HTML <b>. Формат:\n\n"
            "📊 <b>НЕДЕЛЯ · ИТОГИ</b>\n"
            + ("━" * 18) + "\n\n"
            "<b>Матвей:</b> <главное про сон/кормления/подгузники — 2-3 строки>\n"
            "<b>Мы:</b> <про сон Марины и Евгения, отклонения — 1-2 строки>\n"
            "<b>Здоровье:</b> <прививки/лекарства/симптомы за неделю — 1 строка>\n"
            "<b>Авто:</b> <заправки, расход — 1 строка>\n\n"
            "🔍 <b>Что заметил:</b> <1-2 наблюдения-паттерна, только если реально видны в цифрах. "
            "Примеры хороших: «Матвей 3 раза просыпался в 03:00 — стоит показать педиатру», "
            "«Расход авто вырос с 9.5 до 11.2 — вспомни про заправку А92».>\n\n"
            "Правила: не выдумывай, если данных нет — секцию пропускай. "
            "Максимум ~15 строк. Не пиши преамбулу."
        )
        try:
            text = await gemini.complete(
                system=system,
                messages=[{"role": "user", "content": _json.dumps(insights, ensure_ascii=False)}],
                max_tokens=700,
            )
            return (text or "").strip() or "📊 Неделя без явных паттернов."
        except Exception:
            log.exception("altron_weekly_llm_failed")
            return "📊 Не смог собрать недельный отчёт."

    @staticmethod
    def _format_start_card(region: str, started_at: str) -> str:
        try:
            dt = datetime.fromisoformat(started_at)
            hm = dt.strftime("%H:%M")
        except Exception:
            hm = "?"
        return (
            f"🚨 <b>АЛЬТРОН · ТРЕВОГА</b>\n"
            f"📍 {region} · объявлена в {hm}\n"
            + "━" * 18
            + "\n\n⏳ Собираю данные из мониторинга…\n"
            "<i>Обновлю карточку как только пойдёт инфа что и куда летит.</i>"
        )

    def _format_altron_card(
        self, digest: dict, region: str, started_at: str, sources: list[str],
    ) -> str:
        """Информативная карточка Альтрона (отличается от штабной).

        Показывает: оценку угрозы для нас, что летит, курс, ETA, прилёты,
        соседние регионы и — главное — источники из которых собрана инфа.
        """
        try:
            dt = datetime.fromisoformat(started_at)
            hm = dt.strftime("%H:%M")
            duration_min = max(0, int((datetime.now(dt.tzinfo) - dt).total_seconds() / 60))
        except Exception:
            hm = "?"
            duration_min = 0

        weapons = digest.get("weapons") or []
        targets = digest.get("targets") or []
        eta = digest.get("eta") or []
        hits = digest.get("hits") or []
        others = digest.get("other_regions") or []

        # Оценка угрозы для НАС (Одесса)
        threat_level, threat_label = _assess_threat(region, targets, hits, weapons)

        lines: list[str] = []
        lines.append(f"🚨 <b>АЛЬТРОН · ТРЕВОГА</b>")
        lines.append(f"📍 {region} · с {hm} ({duration_min} мин)")
        lines.append("━" * 18)
        lines.append("")
        lines.append(f"{threat_level} <b>ОЦЕНКА:</b> {threat_label}")

        if weapons:
            lines.append("")
            lines.append("✈ <b>ЧТО ЛЕТИТ:</b>")
            for w in weapons:
                t = w.get("type", "?")
                c = w.get("count")
                o = w.get("origin", "")
                row = f"• {t}"
                if c is not None:
                    row += f" × {c}"
                if o:
                    row += f" ({o})"
                lines.append(row)

        if targets:
            lines.append("")
            lines.append("🎯 <b>КУРС:</b>")
            for t in targets:
                lines.append(f"• {t}")

        if eta:
            lines.append("")
            lines.append("⏱ <b>ПОДЛЁТ:</b>")
            for e in eta:
                lines.append(f"• {e.get('weapon','?')} — {e.get('arrival_time','?')}")

        if hits:
            lines.append("")
            lines.append("💥 <b>ПРИЛЁТЫ:</b>")
            for h in hits:
                loc = h.get("location", "?")
                det = h.get("detail", "")
                confirmed = h.get("confirmed", False)
                mark = "" if confirmed else "  <i>(не подтверждено)</i>"
                row = f"• {loc}"
                if det:
                    row += f" — {det}"
                lines.append(row + mark)

        if others:
            lines.append("")
            lines.append("⚠ <b>СОСЕДИ:</b>")
            for o in others:
                reg = o.get("region", "?")
                tgt = o.get("target", "")
                ws = o.get("weapons") or []
                ws_txt = ", ".join(
                    f"{w.get('type','?')}×{w.get('count','?')}" for w in ws
                )
                row = f"• {reg}"
                if ws_txt:
                    row += f" — {ws_txt}"
                if tgt:
                    row += f" → {tgt}"
                lines.append(row)

        if not (weapons or targets or eta or hits or others):
            lines.append("")
            lines.append("<i>Пока без деталей — каналы ещё молчат.</i>")

        lines.append("")
        lines.append("━" * 18)
        if sources:
            lines.append(f"📡 <b>Источники:</b> {', '.join(sources[:6])}")
        else:
            lines.append("📡 <b>Источники:</b> —")
        lines.append(f"🔄 <i>Обн. {datetime.now(dt.tzinfo if isinstance(dt, datetime) else None).strftime('%H:%M:%S') if isinstance(dt, datetime) else '?'}</i>")
        return "\n".join(lines)

    def _format_altron_endcard(
        self, region: str, started_at: str, duration_min: int,
        digest: dict, sources: list[str],
    ) -> str:
        """Карточка ОТБОЯ. Показывает: длилась столько-то, итог по прилётам."""
        try:
            dt_start = datetime.fromisoformat(started_at)
            start_hm = dt_start.strftime("%H:%M")
            end_hm = datetime.now(dt_start.tzinfo).strftime("%H:%M")
        except Exception:
            start_hm = "?"
            end_hm = "?"

        hits = (digest or {}).get("hits") or []
        weapons = (digest or {}).get("weapons") or []

        lines: list[str] = []
        lines.append("✅ <b>АЛЬТРОН · ОТБОЙ</b>")
        lines.append(f"📍 {region} · {start_hm} → {end_hm} · длилось {duration_min} мин")
        lines.append("━" * 18)
        lines.append("")
        if hits:
            lines.append("💥 <b>ЗА ТРЕВОГУ БЫЛО:</b>")
            for h in hits:
                loc = h.get("location", "?")
                det = h.get("detail", "")
                confirmed = h.get("confirmed", False)
                mark = "" if confirmed else " <i>(не подтв.)</i>"
                row = f"• {loc}"
                if det:
                    row += f" — {det}"
                lines.append(row + mark)
        else:
            if weapons:
                lines.append("<b>Прилётов не зафиксировано.</b>")
                w_txt = ", ".join(
                    f"{w.get('type','?')}×{w.get('count','?')}" for w in weapons
                )
                lines.append(f"Пролетало: {w_txt}")
            else:
                lines.append("<b>Прилётов не зафиксировано.</b> Спокойно.")

        lines.append("")
        lines.append("━" * 18)
        if sources:
            lines.append(f"📡 <b>Источники:</b> {', '.join(sources[:6])}")
        else:
            lines.append("📡 <b>Источники:</b> —")
        return "\n".join(lines)
