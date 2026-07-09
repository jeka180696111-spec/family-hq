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
from src.orchestrator.dispatcher import Dispatcher, DispatchResult, AgentTask
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
from src.agents.butler import ButlerAgent
from src.agents.navigator import NavigatorAgent
from src.scheduler.backup import register_backup_job
from src.scheduler.healthcheck import register_healthcheck_jobs
from src.scheduler.reminders import register_reminder_jobs
from src.scheduler.sleep_predictor import SleepPredictor, register_sleep_predictor_job
from src.scheduler.sleep_reactor import SleepReactor, register_sleep_reactor_job
from src.scheduler.evening_recap import register_evening_recap_job
from src.scheduler.family_style import register_family_style_job

log = structlog.get_logger()

_shutdown_event: asyncio.Event | None = None


async def _transcribe_voice(message: Any, settings: Any) -> str:
    """Download a Telethon voice/audio message and run Whisper. Returns text or ''."""
    import tempfile
    from src.integrations.transcribe import TranscribeClient
    client = TranscribeClient.from_settings(settings)
    if not client:
        log.info("voice_skip_no_openai_key")
        return ""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        local_path = tmp.name
    try:
        await message.download_media(file=local_path)
    except Exception:
        log.exception("voice_download_failed")
        return ""
    try:
        return await client.transcribe(local_path)
    finally:
        try:
            import os
            os.unlink(local_path)
        except Exception:
            pass


def _has_photo_media(message: Any) -> bool:
    """Detect photo-like media in a Telethon message robustly.

    Covers: native compressed photo (MessageMediaPhoto), document with
    image/* mime (uncompressed gallery upload), and the fallback case
    where the user-bot returns photo via message.media but neither
    message.photo nor type checks match — last resort scan of repr.
    """
    media = getattr(message, "media", None)
    if media is None:
        return False
    cls_name = type(media).__name__
    if "Photo" in cls_name:  # MessageMediaPhoto, Photo, etc.
        return True
    doc = getattr(media, "document", None)
    mime = getattr(doc, "mime_type", "") if doc else ""
    if mime.startswith("image/"):
        return True
    # Last-resort: voice/audio explicitly excluded; everything else
    # with a media attribute may be a photo our type checks missed.
    if (getattr(message, "voice", None) or getattr(message, "audio", None)
            or getattr(message, "video", None) or getattr(message, "sticker", None)):
        return False
    return True


# ─── Media-group cache ─────────────────────────────────────────────
# Telegram albums deliver each photo as a separate update. Only the FIRST
# photo carries the caption. We cache the branch decision (medical / baby)
# per grouped_id so siblings inherit it.
import time as _time_mod
_MEDIA_GROUP_CACHE: dict[int, dict] = {}
_MEDIA_GROUP_TTL = 120  # seconds


def _now_ts() -> float:
    return _time_mod.time()


def _media_group_evict_old(cache: dict) -> None:
    now = _now_ts()
    stale = [k for k, v in cache.items() if now - v.get("ts", 0) > _MEDIA_GROUP_TTL]
    for k in stale:
        cache.pop(k, None)


async def _handle_baby_photo(
    message: Any, caption: str, agents: dict, memory: Any, settings: Any,
) -> dict:
    """Download a Telegram photo, archive to Drive + DB via baby_photos module,
    and have Няня acknowledge in the chat. Returns the archive result dict
    so the caller can surface the precise age/path to the LLM."""
    import os as _os
    import tempfile
    from src.integrations.baby_photos import archive_photo
    from src.integrations.drive import DriveClient
    log.info("photo_handler_started")
    drive_client = DriveClient.from_settings(settings)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        local_path = tmp.name
    try:
        await message.download_media(file=local_path)
        size = _os.path.getsize(local_path) if _os.path.exists(local_path) else 0
        log.info("photo_downloaded", path=local_path, size=size)
    except Exception:
        log.exception("photo_download_failed")
        nanny = agents.get("nanny")
        if nanny:
            try:
                await nanny.send("📸 Получила фото, но не смогла скачать из Telegram.")
            except Exception:
                pass
        return {}

    # Classify FIRST — exactly 3 types: baby / receipt / medical.
    from src.integrations.baby_photos import classify_photo
    category = await classify_photo(local_path)
    log.info("photo_classified", category=category)

    if category == "receipt":
        # Чек → отдельный пайплайн, не в архив Матвея
        nanny = agents.get("nanny")
        from src.integrations.receipt_photos import (
            archive_receipt, format_summary, parse_receipt,
        )
        parsed = await parse_receipt(local_path)
        upload = await archive_receipt(local_path, parsed, drive_client)
        if nanny:
            try:
                await nanny.send(format_summary(parsed, upload.get("drive_url")))
            except Exception:
                log.exception("receipt_ack_failed")
        try:
            _os.unlink(local_path)
        except Exception:
            pass
        return {"category": "receipt", "_branch": "receipt", "parsed": parsed,
                "drive_url": upload.get("drive_url")}

    if category == "medical":
        # Vision увидел медицинский документ (бланк/УЗИ/заключение)
        # даже без ключевых слов в подписи. Передаём в Айболитский
        # пайплайн — он сам перекачает фото и сделает структурный OCR.
        try:
            _os.unlink(local_path)
        except Exception:
            pass
        med_result = await _handle_medical_photo(
            message, caption, agents, memory, settings,
        ) or {}
        med_result["_branch"] = "medical"
        med_result["category"] = "medical"
        return med_result

    # baby / unknown → стандартный архив малыша
    result = await archive_photo(local_path, caption, drive_client, memory)
    result["category"] = category

    # Drive failed? Try Telegram channel archive as fallback
    tg_archive_id = None
    tg_archive_err = None
    if not result.get("drive_id") and getattr(settings, "baby_photo_archive_channel_id", 0):
        from src.integrations.tg_archive import archive_to_telegram
        # Use bot_manager to send — get any agent (devops bot is most reliable)
        bot_manager = None
        for ag in agents.values():
            bm = getattr(ag, "_bots", None)
            if bm:
                bot_manager = bm
                break
        if bot_manager:
            tg_result = await archive_to_telegram(
                bot_manager, "devops",
                settings.baby_photo_archive_channel_id,
                local_path, caption,
            )
            tg_archive_id = tg_result.get("message_id")
            tg_archive_err = tg_result.get("error")

    nanny = agents.get("nanny")
    if nanny:
        try:
            if result.get("drive_id"):
                ack = (
                    f"📸 Фото сохранено · {result['age']}\n"
                    f"☁️ Drive: загружено"
                )
            elif tg_archive_id:
                ack = (
                    f"📸 Фото сохранено · {result['age']}\n"
                    f"📦 Архив: Telegram (msg {tg_archive_id})\n"
                    f"⚠️ Drive недоступен — SA не имеет storage quota на личном Gmail."
                )
            elif result.get("error") == "drive_not_configured":
                ack = (
                    f"📸 Фото получено · {result['age']}\n"
                    "⚠️ Drive не настроен (нет SA или ROOT folder). "
                    "Файл записан в БД, но не в облако."
                )
            else:
                err = (result.get("error") or "")[:400]
                ack = (
                    f"📸 Фото получено · {result['age']}\n"
                    f"⚠️ Drive upload failed:\n<code>{err}</code>"
                )
                if tg_archive_err:
                    ack += f"\n⚠️ TG archive: <code>{tg_archive_err[:100]}</code>"
            await nanny.send(ack)
        except Exception:
            log.exception("baby_photo_ack_failed")
    return result


async def _handle_medical_photo(
    message: Any, caption: str, agents: dict, memory: Any, settings: Any,
    sibling: bool = False,
) -> dict:
    """Read a medical document photo (УЗИ/анализы/заключение), interpret
    via vision LLM, archive to the right person's Drive folder, and log
    a short diary entry.

    For Telegram albums: each photo is OCR'd separately, but the final
    Айболит summary + diary entry is debounced — sent only after all
    siblings of the album have been processed (6-second silence after
    the last photo). This way the conclusion photo (often the LAST one
    in the album) gets included in the final analysis."""
    import asyncio
    import os as _os
    import tempfile
    from src.integrations.drive import DriveClient
    from src.integrations.medical_photos import (
        archive_medical_photo, detect_person,
    )
    from src.integrations.gemini_client import GeminiClient
    log.info("medical_photo_handler_started", sibling=sibling)
    drive_client = DriveClient.from_settings(settings)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        local_path = tmp.name
    try:
        await message.download_media(file=local_path)
    except Exception:
        log.exception("medical_photo_download_failed")
        return {}

    person = detect_person(caption)
    grouped_id = getattr(message, "grouped_id", None)

    # 1) Raw OCR on every photo (cheap, gets the text on the page)
    raw_ocr = ""
    gemini = GeminiClient.from_settings(settings)
    if gemini:
        try:
            raw_ocr = await gemini.vision_complete(
                image_path=local_path,
                prompt=(
                    "Распознай ВЕСЬ текст на изображении медицинского "
                    "документа дословно. Сохрани структуру строк. "
                    "Если это УЗИ-снимок без текста — кратко опиши что "
                    "видишь (орган, что измеряется)."
                ),
                max_tokens=1200,
            )
        except Exception:
            log.exception("medical_ocr_failed")

    # 2) Upload to per-person Drive folder
    upload = await archive_medical_photo(
        local_path, caption, person, raw_ocr, drive_client,
    )

    try:
        _os.unlink(local_path)
    except Exception:
        pass

    # 3a) Solo medical photo (not part of an album) — finalize now.
    if not grouped_id:
        await _finalize_medical_album(
            person=person,
            person_label=upload["person_label"],
            caption=caption,
            ocr_chunks=[raw_ocr] if raw_ocr else [],
            uploads=[upload],
            agents=agents,
            settings=settings,
        )
        return {
            "person": person,
            "person_label": upload["person_label"],
            "drive_url": upload.get("drive_url"),
            "drive_id": upload.get("drive_id"),
        }

    # 3b) Album member — push OCR into the group buffer and (re)schedule
    #     a debounced finalizer. The last photo to arrive wins; we wait
    #     6 seconds of silence then summarize all collected OCR.
    entry = _MEDIA_GROUP_CACHE.setdefault(grouped_id, {
        "branch": "medical",
        "person": person,
        "person_label": upload["person_label"],
        "caption": caption,
        "ocr_chunks": [],
        "uploads": [],
        "ts": _now_ts(),
    })
    # Ensure schema completeness even if cache entry was pre-seeded by main.
    entry.setdefault("ocr_chunks", [])
    entry.setdefault("uploads", [])
    if not entry.get("person_label"):
        entry["person_label"] = upload["person_label"]
    if raw_ocr:
        entry["ocr_chunks"].append(raw_ocr)
    entry["uploads"].append(upload)
    entry["ts"] = _now_ts()
    if not entry.get("caption") and caption:
        entry["caption"] = caption

    # Cancel any pending finalize task and reschedule
    pending = entry.get("flush_task")
    if pending and not pending.done():
        pending.cancel()

    async def _delayed_flush() -> None:
        try:
            await asyncio.sleep(6.0)
            data = _MEDIA_GROUP_CACHE.get(grouped_id)
            if not data:
                return
            await _finalize_medical_album(
                person=data["person"],
                person_label=data["person_label"],
                caption=data.get("caption", ""),
                ocr_chunks=data.get("ocr_chunks", []),
                uploads=data.get("uploads", []),
                agents=agents,
                settings=settings,
            )
            _MEDIA_GROUP_CACHE.pop(grouped_id, None)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("medical_album_flush_failed")

    entry["flush_task"] = asyncio.create_task(_delayed_flush())

    return {
        "person": person,
        "person_label": upload["person_label"],
        "drive_url": upload.get("drive_url"),
        "drive_id": upload.get("drive_id"),
        "deferred": True,
    }


async def _finalize_medical_album(
    *, person: str, person_label: str, caption: str,
    ocr_chunks: list[str], uploads: list[dict],
    agents: dict, settings: Any,
) -> None:
    """After all album siblings are processed, combine OCR texts, ask the
    vision LLM for ONE structured interpretation, send it to chat as
    Айболит, and write a single diary entry."""
    from src.integrations.gemini_client import GeminiClient
    from src.integrations.medical_photos import _VISION_SYSTEM

    combined_text = "\n\n--- ФОТО ---\n\n".join(
        c.strip() for c in ocr_chunks if c and c.strip()
    )

    interpretation = ""
    gemini = GeminiClient.from_settings(settings)
    if gemini and combined_text:
        try:
            interpretation = await gemini.complete(
                system=_VISION_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Подпись пользователя: «{caption or '—'}»\n\n"
                        f"Распознанный текст со всех фото медицинского "
                        f"документа (склеен по фоткам):\n\n{combined_text}\n\n"
                        "Сделай итоговое заключение по инструкции."
                    ),
                }],
                max_tokens=900,
            )
        except Exception:
            log.exception("medical_album_interpret_failed")

    # Write diary entry
    diary_summary = ""
    try:
        from src.integrations.sheets import SheetsClient
        from src.utils.time import now_kyiv as _now_kyiv
        sa = getattr(settings, "google_service_account_json", "")
        baby_sheet_id = getattr(settings, "sheet_baby_id", "")
        if sa and baby_sheet_id:
            sheets = SheetsClient(
                service_account_info=sa,
                baby_sheet_id=baby_sheet_id,
                finance_sheet_id=getattr(settings, "sheet_finance_id", ""),
            )
            # Pull the line after «📝 Вывод:» if the LLM followed the
            # structured format we asked for; otherwise pull the first
            # non-trivial line that isn't a disclaimer / refusal.
            def _pick_diary_line(text: str) -> str:
                lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
                # Priority 1: the line that follows «📝 Вывод:» or contains "Вывод:"
                for i, ln in enumerate(lines):
                    if "вывод" in ln.lower():
                        # take the rest of this line after the colon, or next line
                        after = ln.split(":", 1)[-1].strip() if ":" in ln else ""
                        if len(after) > 5:
                            return after
                        if i + 1 < len(lines):
                            return lines[i + 1]
                # Priority 2: skip LLM disclaimers and headers, take first useful sentence
                bad_starts = (
                    "к сожалению", "не могу", "извин",
                    "📄", "📅", "🔍", "📝", "⚠️", "пациент", "что:", "дата:",
                )
                for ln in lines:
                    if not any(ln.lower().startswith(b) for b in bad_starts):
                        return ln
                return lines[0] if lines else ""

            picked = _pick_diary_line(interpretation)[:200]
            diary_summary = (
                f"{person_label}: {picked}"
                if picked
                else f"{person_label}: медицинский документ загружен"
            )
            await sheets.append_baby_diary(
                kind="note",
                event="🏥 Медицинский документ",
                time=_now_kyiv(),
                author="family_hq",
                details=diary_summary,
            )
    except Exception:
        log.exception("medical_album_diary_failed")

    # Reply in chat (Айболит's voice with Няня as fallback)
    aibolit = agents.get("health")
    nanny = agents.get("nanny")
    header_bot = aibolit or nanny
    if not header_bot:
        return
    try:
        lines = [f"🩺 <b>{person_label}</b>"]
        if len(uploads) > 1:
            lines.append(f"<i>фото в альбоме: {len(uploads)}</i>")
        if interpretation:
            lines.append(interpretation.strip())
        elif combined_text:
            lines.append("⚠️ Распознал текст, но не удалось структурировать (LLM упал).")
        else:
            lines.append("⚠️ Не удалось распознать содержимое документа.")
        # Drive links + explicit count of failures
        drive_lines = [
            f'☁️ <a href="{u["drive_url"]}">Фото {i+1}</a>'
            for i, u in enumerate(uploads) if u.get("drive_url")
        ]
        failed = [
            (i + 1, u.get("error") or "unknown")
            for i, u in enumerate(uploads) if not u.get("drive_url")
        ]
        if drive_lines:
            lines.append("\n" + " · ".join(drive_lines))
        if failed:
            for idx, err in failed:
                lines.append(f"⚠️ Фото {idx} не загрузилось: <code>{err[:160]}</code>")
        if diary_summary:
            lines.append("📓 Записано в дневник.")
        await header_bot.send("\n".join(lines))
    except Exception:
        log.exception("medical_album_reply_failed")


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

        # Mark «юзер пишет сейчас» — авто-пуши (sleep_predictor, runtime
        # и т.п.) будут откладываться на 90 секунд, чтобы не вклиниваться
        # в активный разговор.
        try:
            from src.utils.chat_activity import mark_user_message
            mark_user_message()
        except Exception:
            pass

        # Slash-command routing: expand short commands into full LLM prompts
        # so existing dispatcher/agents pick them up naturally.
        text = _expand_slash_command(text)
        message_id = getattr(message, "id", 0)

        # Authorization check
        if user_id and not access_control.is_owner(user_id):
            log.warning("unauthorized_message", user_id=user_id)
            return

        # Photo intake — baby photo memory: if message has a photo, archive it.
        # Telethon: message.photo OR message.media of certain types.
        has_photo = bool(getattr(message, "photo", None)) or _has_photo_media(message)
        log.info(
            "message_attrs",
            has_text=bool(text.strip()),
            has_photo=has_photo,
            has_voice=bool(getattr(message, "voice", None)),
            has_audio=bool(getattr(message, "audio", None)),
            has_document=bool(getattr(message, "document", None)),
            has_media=bool(getattr(message, "media", None)),
        )
        if has_photo:
            # Immediate ack so user sees the hook fired even if archive fails
            nanny_for_ack = agents.get("nanny")
            if nanny_for_ack:
                try:
                    await nanny_for_ack.send("📥 Принято фото, обрабатываю…")
                except Exception:
                    pass

            # Medical document branch — УЗИ, анализы, эпикриз, заключение…
            # Route to Айболит's vision pipeline, save under per-person folder,
            # and append a short note to the diary.
            archive_result = {}
            from src.integrations.medical_photos import is_medical_photo, detect_person
            # Telegram albums: only the FIRST photo carries the caption,
            # siblings come without text. Cache the branch decision per
            # grouped_id so all photos in the album land in the right folder.
            grouped_id = getattr(message, "grouped_id", None)
            inherit_medical = False
            inherit_person = "matvey"
            inherit_caption = ""
            if grouped_id:
                cache = _MEDIA_GROUP_CACHE
                _media_group_evict_old(cache)
                hit = cache.get(grouped_id)
                if hit and hit.get("branch") == "medical":
                    inherit_medical = True
                    inherit_person = hit.get("person", "matvey")
                    inherit_caption = hit.get("caption", "") or text

            if is_medical_photo(text) or inherit_medical:
                # Pre-mark the album as medical so concurrent siblings
                # arriving in parallel ALL see the medical flag in cache
                # — Telegram delivers album members nearly simultaneously.
                if grouped_id and not inherit_medical:
                    _MEDIA_GROUP_CACHE.setdefault(grouped_id, {
                        "branch": "medical",
                        "person": detect_person(text),
                        "person_label": "",
                        "caption": text,
                        "ocr_chunks": [],
                        "uploads": [],
                        "ts": _now_ts(),
                    })
                effective_caption = text if not inherit_medical else inherit_caption
                try:
                    archive_result = await _handle_medical_photo(
                        message, effective_caption, agents, memory, settings,
                        sibling=inherit_medical,
                    ) or {}
                    archive_result["_branch"] = "medical"
                except Exception:
                    log.exception("medical_photo_handle_failed")
                    if nanny_for_ack:
                        try:
                            await nanny_for_ack.send("🏥 Не получилось обработать медицинский документ — проверь логи.")
                        except Exception:
                            pass
            else:
                try:
                    archive_result = await _handle_baby_photo(message, text, agents, memory, settings) or {}
                except Exception:
                    log.exception("baby_photo_handle_failed")
                    if nanny_for_ack:
                        try:
                            await nanny_for_ack.send("📸 Не получилось сохранить фото — проверь логи Drive.")
                        except Exception:
                            pass
            # Annotate text for LLM dispatch with EXACT age the system computed
            # from the caption date, so the LLM doesn't hallucinate based on
            # today's age (this prevents "6 мес" replies on a 5-мес photo).
            if archive_result.get("_branch") in ("medical", "receipt"):
                # Either Айболит already replied with the interpretation,
                # or receipt was archived with its own summary — no need
                # for a second LLM round.
                return
            if archive_result.get("skipped") and archive_result.get("category"):
                # Vision categorised the photo as something we explicitly
                # don't process — Няня already said so, skip LLM.
                return
            archived_age = archive_result.get("age") or ""
            age_hint = f"возраст на этом фото: {archived_age}." if archived_age else ""
            sys_note = (
                "[📷 СИСТЕМА: фото архивировано. "
                f"{age_hint} НЕ выдумывай возраст — используй точно эту цифру. "
                "Не повторяй информацию про сохранение/Drive — это уже отправлено отдельным сообщением.]"
            ) if archived_age else "[📷 в сообщении было фото — система пытается архивировать]"
            text = (f"{sys_note}\n{text}" if text.strip() else sys_note)
            # Do NOT return — continue normal text flow so caption gets dispatched too

        # Voice / audio intake — transcribe via Whisper and use as text
        has_voice = bool(getattr(message, "voice", None) or getattr(message, "audio", None))
        if has_voice:
            log.info("voice_message_received", user_id=user_id,
                     has_key=bool(getattr(settings, "openai_api_key", "")))
        if not text.strip() and has_voice:
            try:
                transcript = await _transcribe_voice(message, settings)
            except Exception:
                log.exception("voice_transcribe_failed")
                transcript = ""
            if transcript:
                text = transcript
                log.info("voice_transcribed", text=transcript[:80])
            else:
                log.warning("voice_transcribe_empty")

        if not text.strip():
            return

        log.info("message_received", user_id=user_id, text=text[:50])

        # Auto-detect Nova Poshta TTN (14 digits) anywhere in the text and
        # start tracking — covers pasted SMS from NP or just the bare number
        try:
            import re
            ttns = re.findall(r"\b\d{14}\b", text)
            if ttns:
                from src.scheduler.parcels import poll_parcels  # ensure module loaded
                devops_agent = agents.get("devops")
                for ttn in set(ttns):
                    if devops_agent:
                        try:
                            await devops_agent._parcel_track(
                                ttn=ttn, title="", member="family",
                            )
                        except Exception:
                            log.exception("auto_ttn_track_failed", ttn=ttn)
        except Exception:
            log.exception("ttn_autodetect_failed")

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

        # Reply-to detection — если юзер ответил Reply на чьё-то
        # сообщение, форсим маршрутизацию только этому агенту.
        forced_agent = None
        # Прямое обращение по имени в начале сообщения
        # («Дворецкий, привет», «Няня, как малыш») — форсим маршрутизацию.
        direct_addr = _find_addressed_agent(text, exclude=None)
        if direct_addr:
            forced_agent = direct_addr
            log.info("direct_address_detected", agent=direct_addr, preview=text[:60])
        reply_to_id = getattr(message, "reply_to_msg_id", None)
        if reply_to_id:
            try:
                from sqlalchemy import select
                from src.db.models import Message
                async with memory._engine.connect() as conn:
                    row = (await conn.execute(
                        select(Message).where(Message.tg_message_id == reply_to_id).limit(1)
                    )).first()
                if row and row.agent_id:
                    forced_agent = row.agent_id
                    log.info("reply_to_agent_detected", agent=forced_agent, reply_to=reply_to_id)
            except Exception:
                log.exception("reply_to_lookup_failed")

        # Continuation: если предыдущий агент задал юзеру вопрос
        # («уточни бюджет?», «какую сцену?»), а юзер прислал короткий
        # ответ («до 10к», «26», «да»), маршрутизируем на того же агента.
        if not forced_agent:
            try:
                recent = await context.get_recent(3)
                if recent:
                    last = recent[-1]
                    last_agent = getattr(last, "agent_id", None)
                    last_text = (getattr(last, "text", "") or "").strip()
                    if last_agent and last_text.endswith(("?", "?!", "?")):
                        if len(text.strip()) <= 40:
                            forced_agent = last_agent
                            log.info("continuation_detected", agent=last_agent, reply=text[:40])
            except Exception:
                pass

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
            forced_agent=forced_agent,
        )

    except Exception:
        log.exception("message_handler_error")


_MAX_CHAIN_DEPTH = 3

# ─── Slash and reaction shortcuts ───────────────────────────────────
_SLASH_EXPAND = {
    "/profile": "Прораб, покажи family_wiki (всё)",
    "/wiki": "Прораб, покажи family_wiki (всё)",
    "/status": "Прораб, system_status",
    "/cost": "Прораб, cost_report за 30 дней",
    "/shopping": "Ежедневник, list_shopping — что нужно купить?",
    "/turn": "Няня, whose_turn_tonight — чья очередь ночью?",
    "/handoff": "Няня, babysitter_handoff — собери сводку для бабушки",
    "/news": "Дозорный, get_recent_news за 3 часа",
    "/alerts": "Дозорный, get_recent_alerts за 24 часа",
    "/modes": "Прораб, list_active_modes",
    "/docs": "Прораб, list_documents — покажи документы",
    "/subs": "Прораб, list_subscriptions — покажи подписки",
    "/light": "Прораб, power_outage_stats за неделю",
    "/devices": "Прораб, list_smart_devices",
    "/sos": "Прораб, покажи family_wiki emergency",
    "/sleep": "Айболит, parent_sleep_stats за 7 дней",
    "/foods": "Айболит, list_food_reactions",
    "/help": "Прораб, helper",
    "💧": "Няня, поменяли подгузник сейчас",
    "🍼": "Няня, кормление сейчас",
    "😴": "Няня, уснул сейчас",
    "🌅": "Няня, проснулся сейчас",
}


def _expand_slash_command(text: str) -> str:
    """Map short commands to natural-language prompts so the existing pipeline handles them."""
    if not text:
        return text
    stripped = text.strip()
    if stripped in _SLASH_EXPAND:
        return _SLASH_EXPAND[stripped]
    # /something arg → look up base and prepend
    if stripped.startswith("/"):
        head = stripped.split()[0]
        if head in _SLASH_EXPAND:
            rest = stripped[len(head):].strip()
            return _SLASH_EXPAND[head] + (f" {rest}" if rest else "")
    return text


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


_BUTLER_HOME_HITS = [
    # Умный дом / устройства
    "кондер", "кондиц", "бойлер", "телевизор", " тв ", "розетк",
    "датчик", "температур", "влажност", "свет включ", "свет выкл",
    "выключи свет", "включи свет", "сцен", "smart life", "tuya",
    "пылесос", "робот пылесос",
    # Инвертор / электричество
    "инвертор", "батаре", "солнце", "солнечн", "автономност",
    "света нет", "свет пропал", "отключен", "света дали", "свет дали",
    "генерац", "заряд",
    # Сценарии
    "уехал из дома", "я дома", "еду домой", "приеду к", "возвращаюсь к",
]

_BUTLER_SHOP_HITS = [
    "купи", "купить", "покупк", "найди в магазин", "где купить",
    "какое лучше", "какую лучше", "какой лучше", "выбери",
    "заказ", "закажи",
    # Товарные существительные — сигнал что юзер хочет купить
    "кресл", "коляск", "автокресл", "манеж", "стульчик",
    "подгузник", "смес", "бутылочк", "соск", "пелен",
    "игрушк", "погремушк", "мобил", "ходунк",
    "одежд", "комбинезон", "боди", "шапочк", "носоч", "ботинк",
]


def _is_butler_topic(text: str) -> bool:
    """Дворецкий — умный дом, инвертор, шопер."""
    lower = (text or "").lower()
    # Прямые дом-триггеры
    if any(k in lower for k in _BUTLER_HOME_HITS):
        return True
    # Шоп-триггеры: явные глаголы покупки ИЛИ товарные существительные
    if any(k in lower for k in _BUTLER_SHOP_HITS):
        return True
    # «нужно/нужен/нужна X» — если это не devops-топик (логи/PR/AI),
    # то это скорее всего просьба купить или сделать по дому
    if any(p in lower for p in ("нужно ", "нужен ", "нужна ", "надо ", "хочу купить", "потребует")):
        if not _is_devops_topic(lower):
            return True
    return False


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
    # Butler ловим ПЕРВЫМ — многие домашние команды ("кондер", "бойлер")
    # раньше уходили к Прорабу и он захлебывался.
    if _is_butler_topic(text):
        butler_tasks = [t for t in tasks if t.agent_id == "butler"]
        if butler_tasks:
            return butler_tasks
        # Если диспетчер не поставил butler в список — принудительно перебрасываем на butler
        for t in tasks:
            if t.agent_id == "devops":
                t.agent_id = "butler"
        return [t for t in tasks if t.agent_id == "butler"]
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
    "butler": ["дворецкий", "дворецкому", "дворецкого"],
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
    """Detect if `text` addresses another agent by name AND contains an action verb.

    Также: если сообщение начинается с имени агента и запятой
    («Дворецкий, привет», «Няня, как малыш») — маршрутизируем на
    этого агента даже без action-verb (это прямое обращение).
    """
    if not text:
        return None
    lower = text.lower().strip()
    # Прямое обращение в начале: «Имя, ...» / «Имя ...»
    for agent_id, names in _AGENT_NAME_PATTERNS.items():
        if agent_id == exclude:
            continue
        for name in names:
            if lower.startswith(name + ",") or lower.startswith(name + " ") or lower == name:
                return agent_id
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
    forced_agent: str | None = None,
) -> None:
    """Dispatch a message to agents; if an agent's reply addresses another, recurse."""
    recent = await context.get_recent(8)
    if forced_agent and forced_agent in registry.active_ids():
        # Telegram-Reply на конкретного агента — байпасс диспетчера,
        # отвечает ТОЛЬКО он.
        result = DispatchResult(
            tasks=[AgentTask(
                agent_id=forced_agent, priority="normal",
                reason="telegram_reply_to_agent",
            )],
            is_critical=False, is_settings_command=False,
            intent="reply_to_agent", is_external=False,
        )
    else:
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

    # Load family overrides from DB (location, updated weights, etc.)
    try:
        from sqlalchemy import select
        from src.db.models import FamilyOverride
        from src.utils.family import apply_overrides
        async with engine.begin() as conn:
            rows = list(await conn.execute(select(FamilyOverride)))
        ovr = {r.key: r.value for r in rows}
        apply_overrides(ovr)
        log.info("family_overrides_loaded", count=len(rows))
        # Restore AI provider override that survived previous shutdowns
        try:
            from src.integrations.claude_client import load_override_from_overrides
            load_override_from_overrides(ovr)
        except Exception:
            log.exception("ai_override_restore_failed")
    except Exception:
        log.exception("family_overrides_load_failed")

    # Load family wiki facts — agents read these as shared context
    try:
        from sqlalchemy import select
        from src.db.models import FamilyFact
        from src.utils.family import apply_wiki_facts
        async with engine.begin() as conn:
            rows = list(await conn.execute(select(FamilyFact)))
        apply_wiki_facts([
            {"member": r.member, "key": r.key, "value": r.value} for r in rows
        ])
        log.info("family_wiki_loaded", count=len(rows))
    except Exception:
        log.exception("family_wiki_load_failed")
    memory = SharedMemory(engine)

    # Init integrations
    claude = ClaudeClient(
        primary_key=settings.anthropic_api_key_primary,
        backup_key=settings.anthropic_api_key_backup,
    )
    claude.attach_memory(memory)

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
        # Navigator falls back to devops bot if no dedicated token is set
        "navigator": settings.navigator_bot_token or settings.devops_bot_token,
        # Butler (Дворецкий) — умный дом + шопер. Falls back to devops.
        "butler": settings.butler_bot_token or settings.devops_bot_token,
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
        "health": HealthAgent(**base_args, sheets_client=sheets),
        "devops": DevOpsAgent(**base_args, github_client=github, railway_client=railway),
        "navigator": NavigatorAgent(**base_args),
        "butler": ButlerAgent(**base_args, github_client=github, railway_client=railway),
    }
    # Cross-reference so devops can trigger composite jobs (morning brief etc.)
    agents["devops"]._peer_agents = agents
    agents["navigator"]._peer_agents = agents
    agents["butler"]._peer_agents = agents

    # Load registry from DB
    registry = await AgentRegistry.load_from_db(memory)

    # Access control
    access_control = AccessControl(memory, settings.owner_ids)

    # Orchestrator
    dispatcher = Dispatcher(claude, settings.model_cheap)
    parser = MessageParser(claude, settings.model_cheap)

    # Scheduler
    # Все cron-задания используют Kyiv-time — иначе 22:00 на UTC-сервере
    # стреляет в 01:00 ночи по Киеву (реальный кейс с evening_recap).
    from src.utils.time import KYIV_TZ
    scheduler = AsyncIOScheduler(timezone=KYIV_TZ)
    # Give Navigator a scheduler handle so it can arm one-shot trip jobs
    agents["navigator"]._scheduler = scheduler
    # Standalone morning digests removed — superseded by unified brief at 07:00.
    from src.scheduler.wave3 import (
        register_weekly_digest_job, register_baby_budget_job, register_time_capsule_job,
    )
    register_weekly_digest_job(scheduler, agents["news"], agents["nanny"], memory)
    register_baby_budget_job(scheduler, agents["devops"], memory)
    register_time_capsule_job(scheduler, agents["news"], memory)

    # Web dashboard — read-only state view at /dashboard?token=...
    try:
        if getattr(settings, "dashboard_token", ""):
            import os as _os
            from src.web.dashboard import start_dashboard_server
            port = int(_os.environ.get("PORT", 8080))
            await start_dashboard_server(memory, settings, port)
    except Exception:
        log.exception("dashboard_start_failed")

    # Baby state sync — read Дневник every 5 min and project into BabyState
    try:
        from src.scheduler.baby_sync import register_baby_sync_job, sync_baby_state
        register_baby_sync_job(scheduler, memory, sheets)
        # Trigger first sync immediately so dashboard has data right away
        if sheets:
            asyncio.create_task(sync_baby_state(memory, sheets))
    except Exception:
        log.exception("baby_sync_setup_failed")

    # Nova Poshta — auto-discover new parcels every hour + track active
    try:
        from src.scheduler.parcels import register_parcel_poll_job
        register_parcel_poll_job(scheduler, memory, bot_manager, chat_id, calendar_client)
    except Exception:
        log.exception("parcel_poll_setup_failed")

    # Weekly Family Chronicle PDF every Sunday 20:00
    try:
        from src.integrations.drive import DriveClient
        from src.scheduler.chronicle import register_chronicle_job
        register_chronicle_job(
            scheduler, memory, bot_manager, chat_id,
            DriveClient.from_settings(settings),
        )
    except Exception:
        log.exception("chronicle_setup_failed")


    # Unified morning brief at 07:00 — one message from Прораб with
    # news / weather (clothing + walk window) / baby / plans / systems.
    from src.scheduler.morning_brief import register_morning_brief_job
    register_morning_brief_job(
        scheduler, agents["devops"], agents["news"], agents["nanny"],
        agents["calendar"], memory, at="07:00",
    )

    # Automation engine — evaluates user IF-THEN rules every 5 min
    from src.integrations.automation import AutomationEngine, register_automation_job
    automation_engine = AutomationEngine(memory, bot_manager, chat_id, agents)
    register_automation_job(scheduler, automation_engine)
    # Expose so devops's log_power_outage can trigger rules manually too.
    agents["devops"]._automation = automation_engine

    # Grid watcher — auto-detect power outages via inverter every 60 sec
    try:
        from src.integrations.grid_watcher import GridWatcher, register_grid_watcher_job
        if settings.luxcloud_email and settings.luxcloud_password and settings.lux_inverter_serial:
            grid_watcher = GridWatcher(memory, agents["devops"], bot_manager, chat_id, automation_engine)
            register_grid_watcher_job(scheduler, grid_watcher)
        else:
            log.info("grid_watcher_skipped_no_inverter_env")
    except Exception:
        log.exception("grid_watcher_setup_failed")
    register_backup_job(scheduler, memory, settings.db_path, settings.drive_backup_folder_id, sa_info or {})
    register_healthcheck_jobs(scheduler, claude, memory, bot_manager, chat_id)
    register_reminder_jobs(scheduler, agents["calendar"], bot_manager, chat_id, memory)

    # Прораб notebook: every 5 min check overdue tasks and ping chat.
    # First tick at 30s so the worksheet gets created immediately on deploy.
    try:
        from datetime import timedelta as _td
        from src.utils.time import now_kyiv as _now_kyiv_local
        from src.scheduler.notebook_poll import poll_notebook_overdue
        scheduler.add_job(
            poll_notebook_overdue,
            "interval", minutes=5,
            args=[agents, memory, bot_manager, chat_id],
            id="notebook_poll", coalesce=True, max_instances=1,
            next_run_time=_now_kyiv_local() + _td(seconds=30),
        )
    except Exception:
        log.exception("notebook_poll_register_failed")

    # Family anniversaries — daily 08:00 check for birthdays + wedding
    # + relationship dates. Pre-warns at D-7/D-3/D-1, posts consolidated
    # congrats on the day itself.
    try:
        from src.scheduler.anniversaries import register_anniversary_job
        register_anniversary_job(scheduler, bot_manager, chat_id, memory)
    except Exception:
        log.exception("anniversary_register_failed")

    # One-shot: seed Ukrainian vaccination schedule for Матвей if not yet seeded
    if calendar_client:
        try:
            from src.scheduler.vaccines import register_vaccine_seed_once
            asyncio.create_task(register_vaccine_seed_once(calendar_client, memory))
        except Exception:
            log.exception("vaccine_seed_kickoff_failed")

    # Sleep window predictor — every 5 min checks if Матвей is approaching
    # his age-typical wake window and pushes Marina a soft warning.
    try:
        sleep_predictor = SleepPredictor(
            memory=memory, nanny_agent=agents["nanny"],
            bot_manager=bot_manager, chat_id=chat_id,
        )
        register_sleep_predictor_job(scheduler, sleep_predictor)
    except Exception:
        log.exception("sleep_predictor_register_failed")

    # Sleep reactor — каждые 2 мин сканит Дневник, при новой записи
    # засыпание/пробуждение Няня немедленно комментирует в чат.
    try:
        sleep_reactor = SleepReactor(
            memory=memory, nanny_agent=agents["nanny"],
            bot_manager=bot_manager, chat_id=chat_id,
        )
        register_sleep_reactor_job(scheduler, sleep_reactor)
    except Exception:
        log.exception("sleep_reactor_register_failed")

    # Evening recap — в 22:00 Прораб итожит день и план на завтра.
    try:
        register_evening_recap_job(
            scheduler, agents["devops"], agents.get("calendar"), memory,
        )
    except Exception:
        log.exception("evening_recap_register_failed")

    # Family style memo — еженедельно генерится профайл стиля каждого
    # участника + warm-up через 5 мин после старта (если в БД уже есть
    # последний memo — подгружаем синхронно сейчас).
    try:
        async def _bootstrap_style_cache():
            try:
                from sqlalchemy import select
                from src.db.models import FamilyMode
                from src.utils.family import update_style_cache
                async with memory._engine.connect() as conn:
                    row = (await conn.execute(
                        select(FamilyMode).where(FamilyMode.name == "family_style_memo").limit(1)
                    )).first()
                    if row and row.payload:
                        update_style_cache(row.payload)
                        log.info("family_style_cache_loaded", chars=len(row.payload))
            except Exception:
                log.exception("style_cache_bootstrap_failed")
        asyncio.create_task(_bootstrap_style_cache())
        register_family_style_job(scheduler, agents["devops"], memory)
    except Exception:
        log.exception("family_style_register_failed")

    # Advice tracker — каждые 30 мин оценивает советы старше 12ч,
    # сравнивает с реальностью (фактическая запись в Дневнике).
    try:
        async def _eval_advice():
            try:
                from src.integrations.advice_tracker import evaluate_pending
                sheets = getattr(agents.get("nanny"), "_sheets", None)
                if sheets:
                    await evaluate_pending(memory, sheets)
            except Exception:
                log.exception("advice_eval_tick_failed")
        scheduler.add_job(
            _eval_advice, "interval", minutes=30,
            id="advice_evaluator", replace_existing=True,
            coalesce=True, max_instances=1,
        )
    except Exception:
        log.exception("advice_eval_register_failed")

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
    news_ingestor = NewsIngestor(
        memory,
        bot_manager=bot_manager,
        chat_id=chat_id,
        claude_client=claude,
        model_cheap=settings.model_cheap,
    )
    await news_ingestor.load_tracked_channels()
    userbot.add_news_handler(news_ingestor.handle)


    # Auto-close stale alerts every 5 min
    scheduler.add_job(
        news_ingestor.auto_close_stale,
        "interval",
        minutes=5,
        id="auto_close_stale_alerts",
        replace_existing=True,
    )

    # Graceful shutdown handler
    _shutdown_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown_event.set)

    try:
        await userbot.start()
        log.info("family_hq_started", agents=list(agents.keys()), chat_id=chat_id)

        # UI enhancements: bot menu commands + inline keyboard callbacks
        try:
            from src.integrations.telegram_ui import set_bot_menus, handle_callback, is_enhanced
            await set_bot_menus(bot_manager)
            if is_enhanced():
                async def _cb(cq):
                    await handle_callback(cq, agents, memory, bot_manager, chat_id)
                await bot_manager.start_callback_polling(_cb)
                log.info("ui_enhanced_mode_active")
            else:
                log.info("ui_classic_mode_active")
        except Exception:
            log.exception("ui_setup_failed")

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
