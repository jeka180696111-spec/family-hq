"""Weekly Family Chronicle PDF.

Layout:
  Page 1: cover + (if signal) stats grid + (if signal) nanny note + photos
  Following: feedings (with reactions), vaccines, achievements, outages.

Stats and sections are conditional — empty weeks render no zero rows.
Photos are picked one-per-day, chronological, max 7.
"""
from __future__ import annotations

import io
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

log = structlog.get_logger()


async def generate_weekly_chronicle(
    memory: Any, bot_manager: Any, chat_id: int,
    drive_client: Any,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    force: bool = False,
) -> None:
    """Generate one weekly PDF.

    By default covers the last 7 days. Pass start_dt/end_dt (Kyiv-local)
    to generate a retro chronicle for a different week. Pass force=True
    to bypass the 'must have a photo for every day' check.
    """
    try:
        from src.utils.time import now_kyiv
        end = end_dt or now_kyiv()
        start = start_dt or (end - timedelta(days=7))
        week_number = end.isocalendar()[1]

        photos = await _collect_photos(memory, start, end)

        # Rule: every day in the week must have at least one photo.
        # If a day is missing — warn user and stop. They upload it,
        # then re-trigger.
        photos_days = set((p.get("when") or "")[:10] for p in photos if p.get("when"))
        all_days = []
        cursor = start.date()
        end_date = (end - timedelta(seconds=1)).date()
        while cursor <= end_date:
            all_days.append(cursor.strftime("%Y-%m-%d"))
            cursor += timedelta(days=1)
        missing_days = [d for d in all_days if d not in photos_days]

        if missing_days and not force:
            if bot_manager and chat_id:
                pretty = ", ".join(
                    datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m") for d in missing_days
                )
                try:
                    await bot_manager.send_message(
                        agent_id="devops", chat_id=chat_id,
                        text=(
                            f"📖 <b>Хроника {start.strftime('%d.%m')} — {end.strftime('%d.%m.%Y')}</b>\n\n"
                            f"⚠️ Нет фото за: <b>{pretty}</b>\n\n"
                            f"Загрузи по одному фото за каждый из этих дней "
                            f"(в подписи поставь дату — например «прогулка 03.06»). "
                            f"Затем скажи «сгенерируй хронику» — соберу полный PDF.\n\n"
                            f"Или скажи «сгенерируй хронику force» — соберу с пропусками."
                        ),
                    )
                except Exception:
                    log.exception("chronicle_missing_warn_failed")
            log.info("chronicle_missing_photos", days=missing_days)
            return

        diary_stats = await _collect_diary_stats(start, end)
        feedings = await _collect_feedings(start, end)
        achievements = await _collect_achievements(start, end)
        vaccines = await _collect_vaccines(start, end)
        doctor_visits = await _collect_doctor_visits(start, end)
        growth = await _collect_growth(start, end)
        outages = await _collect_outages(memory, start, end)

        # One photo per day, chronological. Within a day prefer the
        # photo WITH the longest caption (more meaningful), then most
        # recently uploaded.
        photos_by_day: dict[str, dict] = {}
        for p in sorted(photos, key=lambda x: x.get("when") or ""):
            day = (p.get("when") or "")[:10]
            if not day:
                continue
            current = photos_by_day.get(day)
            new_score = (len(p.get("caption") or ""), p.get("when") or "")
            cur_score = (len(current.get("caption") or ""), current.get("when") or "") if current else (-1, "")
            if new_score >= cur_score:
                photos_by_day[day] = p
        daily_photos = sorted(photos_by_day.values(), key=lambda x: x.get("when") or "")
        daily_photos = daily_photos[:7]

        embedded_photo_paths: list[tuple[str, str, str]] = []
        if drive_client and daily_photos:
            for p in daily_photos:
                file_id = p.get("drive_id")
                if not file_id:
                    continue
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                tmp.close()
                if await drive_client.download(file_id, tmp.name):
                    embedded_photo_paths.append((
                        tmp.name,
                        p.get("caption") or "",
                        p.get("when", "")[:10],
                    ))

        has_signal = bool(
            diary_stats.get("feeds") or diary_stats.get("sleep_hours")
            or diary_stats.get("diapers") or feedings or photos
            or achievements
        )
        nanny_note = await _nanny_weekly_note(
            diary_stats=diary_stats, photos=photos, feedings=feedings,
            achievements=achievements, week_number=week_number,
        ) if has_signal else ""

        pdf_bytes = _render_pdf(
            week_number=week_number, start=start, end=end,
            embedded_photos=embedded_photo_paths,
            total_photos=len(photos),
            diary_stats=diary_stats,
            feedings=feedings,
            achievements=achievements,
            vaccines=vaccines,
            doctor_visits=doctor_visits,
            growth=growth,
            outages=outages,
            nanny_note=nanny_note,
        )

        for path, _, _ in embedded_photo_paths:
            try:
                os.unlink(path)
            except Exception:
                pass

        if not pdf_bytes:
            log.info("chronicle_empty_week")
            return

        filename = f"Тиждень_{week_number:02d}_{start.strftime('%Y-%m-%d')}.pdf"
        drive_url = None
        if drive_client:
            try:
                folder_id = await drive_client.ensure_path([
                    "📖 Хроника семьи", str(end.year),
                ])
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_bytes)
                    tmp_path = tmp.name
                try:
                    result = await drive_client.upload(
                        tmp_path, filename, folder_id,
                        description=f"Хроника недели №{week_number}",
                    )
                    drive_url = result.get("url")
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
            except Exception:
                log.exception("chronicle_upload_failed")

        if bot_manager and chat_id:
            lines = [
                f"📖 <b>Семейная хроника · неделя №{week_number}</b>",
                f"📅 {start.strftime('%d.%m')} — {end.strftime('%d.%m.%Y')}",
            ]
            stat_lines = []
            if diary_stats.get("feeds"):
                stat_lines.append(f"🍼 Кормлений: {diary_stats['feeds']}")
            if diary_stats.get("sleep_hours"):
                stat_lines.append(f"😴 Сна всего: ~{diary_stats['sleep_hours']:.0f}ч")
            if diary_stats.get("diapers"):
                stat_lines.append(f"💧 Подгузников: {diary_stats['diapers']}")
            if photos:
                stat_lines.append(f"📸 Фото: {len(photos)} (в PDF — по одному в день)")
            if feedings:
                stat_lines.append(f"🥄 Прикорма: {len(feedings)}")
            if achievements:
                stat_lines.append(f"🌟 Достижений: {len(achievements)}")
            if vaccines:
                stat_lines.append(f"💉 Прививок: {len(vaccines)}")
            if outages:
                total_min = sum(o.get("duration_min") or 0 for o in outages)
                stat_lines.append(
                    f"⚡ Отключений: {len(outages)} (всего {total_min // 60}ч {total_min % 60}мин)"
                )
            if stat_lines:
                lines.append("")
                lines.extend(stat_lines)
            else:
                lines.append("\nДанных пока мало — заполни дневник через Няню, "
                             "следующая хроника будет насыщеннее.")
            if drive_url:
                lines.append(f"\n📂 <a href=\"{drive_url}\">Открыть PDF</a>")
            else:
                lines.append("\n⚠️ PDF не сохранён в Drive")
            try:
                await bot_manager.send_message(
                    agent_id="devops", chat_id=chat_id, text="\n".join(lines),
                )
            except Exception:
                log.exception("chronicle_announce_failed")
        log.info("chronicle_done", week=week_number, photos=len(photos))
    except Exception:
        log.exception("chronicle_failed")


# ─── Nanny narrative ────────────────────────────────────────────────

async def _nanny_weekly_note(
    diary_stats: dict, photos: list, feedings: list,
    achievements: list, week_number: int,
) -> str:
    try:
        from src.config import get_settings
        from src.integrations.claude_client import ClaudeClient
        settings = get_settings()
        client = ClaudeClient(
            primary_key=settings.anthropic_api_key,
            backup_key=settings.anthropic_backup_api_key,
            memory=None, model=settings.claude_model,
        )
        captions = [p.get("caption", "") for p in photos if p.get("caption")]
        feed_lines = []
        for f in feedings[:10]:
            r = f.get("reaction", "") or "—"
            feed_lines.append(f"{f.get('product', '?')} → {r}")
        ach_lines = [f"{a.get('event', '')}" for a in achievements[:8]]
        ctx = (
            f"Неделя №{week_number}.\n"
            f"Кормлений (молоко/смесь): {diary_stats.get('feeds', 0)}\n"
            f"Сна всего: ~{diary_stats.get('sleep_hours', 0):.0f}ч\n"
            f"Подгузников: {diary_stats.get('diapers', 0)}\n"
            f"Фото сделано: {len(photos)}\n"
            f"Подписи к фото: {', '.join(captions[:6]) if captions else 'нет'}\n"
            f"Прикорм: {'; '.join(feed_lines) if feed_lines else 'без нового'}\n"
            f"Достижения: {'; '.join(ach_lines) if ach_lines else 'без новых'}\n"
        )
        system = (
            "Ты — Няня, заботливая и тёплая. Сейчас сводка о неделе малыша "
            "Матвея в семейную хронику-альбом. Напиши 4-6 предложений на "
            "русском в формате тёплого письма для альбома. Без эмодзи, без "
            "хэштегов. Подчеркни 1-2 особенных момента (новый прикорм, "
            "достижение, особенное фото). Тон: душевно, без официоза. НЕ "
            "выдумывай факты, опирайся только на данные. Если данных мало — "
            "пиши коротко."
        )
        text = await client.complete(
            model=settings.claude_haiku_model or "claude-haiku-4-5-20251001",
            system=system,
            messages=[{"role": "user", "content": ctx}],
            max_tokens=400,
        )
        return text.strip()
    except Exception:
        log.exception("nanny_weekly_note_failed")
        return ""


# ─── Data collectors ────────────────────────────────────────────────

# Captions that look medical — chronicle should skip these even if they
# accidentally landed in BabyPhoto (e.g. uploaded before the Vision
# classifier patch routed them to the medical pipeline).
_MEDICAL_CAPTION_HINTS = (
    "узи", "узд", "ехо", "эхо",
    "анализ", "аналіз",
    "эпикриз", "епікриз",
    "заключение", "висновок",
    "диагноз", "діагноз",
    "рентген", "флюорограф", "флг",
    "мрт", "кт", "томограф",
    "осмотр", "огляд",
    "консультация", "консультація",
    "доктор", "лікар", "врач",
    "педиатр", "терапевт", "невролог",
    "медкарт", "карточк",
    "выписка", "виписка",
    "рецепт",
    "проанализир", "проаналізу",  # «Проанализируй и сохрани» → точно мед
)


def _looks_medical(caption: str) -> bool:
    text = (caption or "").lower()
    return any(h in text for h in _MEDICAL_CAPTION_HINTS)


_LEADING_DATE_RE = __import__("re").compile(
    r"^\s*\d{1,2}[.\-/]\d{1,2}(?:[.\-/]\d{2,4})?\s*[—\-:.,]?\s*"
)


def _strip_leading_date(text: str) -> str:
    """Remove a leading DD.MM or DD.MM.YYYY from the caption so chronicle
    doesn't show the same date twice (once in caption, once below)."""
    return _LEADING_DATE_RE.sub("", text or "").strip()


async def _collect_photos(memory: Any, start, end) -> list[dict]:
    from src.db.models import BabyPhoto
    async with memory._engine.connect() as conn:
        rows = list(await conn.execute(
            select(BabyPhoto)
            .where(BabyPhoto.created_at >= start.isoformat())
            .where(BabyPhoto.created_at < end.isoformat())
            .order_by(BabyPhoto.id.desc())
        ))
    out = []
    for r in rows:
        if _looks_medical(r.caption or ""):
            # Strip медицинские документы из хроники малыша
            continue
        out.append({
            "caption": r.caption or "", "age": r.age_label,
            "drive_id": r.drive_file_id, "when": r.created_at,
        })
    return out


async def _collect_diary_stats(start, end) -> dict:
    try:
        from src.config import get_settings
        from src.integrations.sheets import SheetsClient
        s = get_settings()
        if not (s.google_service_account_json and s.sheet_baby_id):
            return {}
        sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")
        try:
            rows = await sheets.get_baby_diary(days=8)
        except Exception:
            log.exception("chronicle_diary_fetch_failed")
            return {}
    except Exception:
        log.exception("chronicle_diary_setup_failed")
        return {}

    feeds = 0
    diapers = 0
    sleep_segments: list[tuple[datetime, str]] = []
    for r in rows:
        d = r.data
        date_s = (d.get("date") or "").strip()
        time_s = (d.get("time") or "00:00").strip()
        dt = None
        for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(f"{date_s} {time_s}", fmt)
                break
            except ValueError:
                continue
        if dt is None:
            continue
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end
        if not (start_naive <= dt < end_naive):
            continue
        kind = (d.get("kind") or "").lower()
        cleaned_kind = kind
        for ch in kind:
            if ch.isalpha():
                break
            cleaned_kind = cleaned_kind[1:]
        cleaned_kind = cleaned_kind.strip()
        event = (d.get("event") or "").lower()
        if cleaned_kind in ("еда", "food", "прикорм"):
            feeds += 1
        elif cleaned_kind in ("подгузник", "diaper"):
            diapers += 1
        elif cleaned_kind in ("сон", "sleep"):
            sleep_segments.append((dt, event))

    sleep_hours = 0.0
    last_sleep_start: datetime | None = None
    for dt, event in sorted(sleep_segments):
        if any(w in event for w in ("уснул", "лёг", "лег", "начал спать")):
            last_sleep_start = dt
        elif any(w in event for w in ("проснул", "встал", "разбудил")) and last_sleep_start:
            delta = (dt - last_sleep_start).total_seconds() / 3600
            if 0 < delta < 14:
                sleep_hours += delta
            last_sleep_start = None

    return {
        "feeds": feeds,
        "diapers": diapers,
        "sleep_hours": sleep_hours,
        "diary_entries": len(rows),
    }


async def _collect_feedings(start, end) -> list[dict]:
    """Прикорм sheet → list of {date, type, product, portion, reaction, details}."""
    try:
        from src.config import get_settings
        from src.integrations.sheets import SheetsClient, _FEEDING_WORKSHEET
        s = get_settings()
        if not (s.google_service_account_json and s.sheet_baby_id):
            return []
        sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")
        if sheets._gc is None:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                s.google_service_account_json,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            sheets._gc = gspread.authorize(creds)

        def _read():
            ws = sheets._gc.open_by_key(s.sheet_baby_id).worksheet(_FEEDING_WORKSHEET)
            return ws.get_all_values()
        try:
            all_rows = await sheets._run_sync(_read)
        except Exception:
            log.exception("chronicle_feedings_read_failed")
            return []
    except Exception:
        log.exception("chronicle_feedings_setup_failed")
        return []

    out = []
    for row in all_rows:
        if len(row) < 4:
            continue
        date_s = (row[1] or "").strip()
        try:
            dt = datetime.strptime(date_s, "%d.%m.%Y")
        except ValueError:
            continue
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end
        if not (start_naive.date() <= dt.date() <= end_naive.date()):
            continue
        out.append({
            "date": date_s,
            "age": row[2] if len(row) > 2 else "",
            "type": row[3] if len(row) > 3 else "",
            "product": row[4] if len(row) > 4 else "",
            "portion": row[5] if len(row) > 5 else "",
            "reaction": row[6] if len(row) > 6 else "",
            "details": row[7] if len(row) > 7 else "",
        })
    return out


async def _collect_achievements(start, end) -> list[dict]:
    """Достижения Матвея: first sat, smiled, rolled over etc.
    Read 'Достижения' sheet directly.
    Columns: num, date, age, event, details, author."""
    try:
        from src.config import get_settings
        from src.integrations.sheets import SheetsClient
        s = get_settings()
        if not (s.google_service_account_json and s.sheet_baby_id):
            return []
        sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")
        if sheets._gc is None:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                s.google_service_account_json,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            sheets._gc = gspread.authorize(creds)

        def _read():
            ws = sheets._gc.open_by_key(s.sheet_baby_id).worksheet("Достижения")
            return ws.get_all_values()
        try:
            all_rows = await sheets._run_sync(_read)
        except Exception:
            log.exception("chronicle_achievements_read_failed")
            return []
    except Exception:
        log.exception("chronicle_achievements_setup_failed")
        return []

    out = []
    for row in all_rows:
        if len(row) < 4:
            continue
        date_s = (row[1] or "").strip()
        try:
            dt = datetime.strptime(date_s, "%d.%m.%Y")
        except ValueError:
            continue
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end
        if not (start_naive.date() <= dt.date() <= end_naive.date()):
            continue
        out.append({
            "date": date_s,
            "age": row[2] if len(row) > 2 else "",
            "event": row[3] if len(row) > 3 else "",
            "details": row[4] if len(row) > 4 else "",
        })
    return out


async def _collect_vaccines(start, end) -> list[dict]:
    try:
        from src.config import get_settings
        from src.integrations.gcalendar import CalendarClient
        s = get_settings()
        if not (s.google_service_account_json and s.calendar_id):
            return []
        cal = CalendarClient(s.google_service_account_json, s.calendar_id)
        events = await cal.list_upcoming(days=7)
    except Exception:
        log.exception("chronicle_vaccines_failed")
        return []
    out = []
    for e in events:
        title = getattr(e, "title", "") or ""
        if "прививк" not in title.lower() and "💉" not in title and "вакц" not in title.lower():
            continue
        out.append({
            "title": title,
            "when": getattr(e, "start", None).isoformat() if getattr(e, "start", None) else "",
        })
    return out


async def _collect_doctor_visits(start, end) -> list[dict]:
    """Read 'Врач' sheet for visits this week. Columns:
    num, date, age, type, doctor/clinic, diagnosis, recommendations."""
    try:
        from src.config import get_settings
        from src.integrations.sheets import SheetsClient
        s = get_settings()
        if not (s.google_service_account_json and s.sheet_baby_id):
            return []
        sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")
        if sheets._gc is None:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                s.google_service_account_json,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            sheets._gc = gspread.authorize(creds)

        def _read():
            ws = sheets._gc.open_by_key(s.sheet_baby_id).worksheet("Врач")
            return ws.get_all_values()
        try:
            all_rows = await sheets._run_sync(_read)
        except Exception:
            log.exception("chronicle_doctor_read_failed")
            return []
    except Exception:
        log.exception("chronicle_doctor_setup_failed")
        return []
    out = []
    for row in all_rows:
        if len(row) < 4:
            continue
        date_s = (row[1] or "").strip()
        try:
            dt = datetime.strptime(date_s, "%d.%m.%Y")
        except ValueError:
            continue
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end
        if not (start_naive.date() <= dt.date() <= end_naive.date()):
            continue
        out.append({
            "date": date_s,
            "age": row[2] if len(row) > 2 else "",
            "type": row[3] if len(row) > 3 else "",
            "doctor": row[4] if len(row) > 4 else "",
            "diagnosis": row[5] if len(row) > 5 else "",
            "notes": row[6] if len(row) > 6 else "",
        })
    return out


async def _collect_growth(start, end) -> list[dict]:
    """Read 'Рост' sheet for measurements this week.
    Columns: date, age, weight_g, height_cm, notes."""
    try:
        from src.config import get_settings
        from src.integrations.sheets import SheetsClient
        s = get_settings()
        if not (s.google_service_account_json and s.sheet_baby_id):
            return []
        sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")
        if sheets._gc is None:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                s.google_service_account_json,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            sheets._gc = gspread.authorize(creds)

        def _read():
            ws = sheets._gc.open_by_key(s.sheet_baby_id).worksheet("Рост")
            return ws.get_all_values()
        try:
            all_rows = await sheets._run_sync(_read)
        except Exception:
            log.exception("chronicle_growth_read_failed")
            return []
    except Exception:
        log.exception("chronicle_growth_setup_failed")
        return []
    out = []
    for row in all_rows:
        if len(row) < 4:
            continue
        date_s = (row[0] or "").strip()
        try:
            dt = datetime.strptime(date_s, "%d.%m.%Y")
        except ValueError:
            continue
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end
        if not (start_naive.date() <= dt.date() <= end_naive.date()):
            continue
        out.append({
            "date": date_s,
            "age": row[1] if len(row) > 1 else "",
            "weight_g": row[2] if len(row) > 2 else "",
            "height_cm": row[3] if len(row) > 3 else "",
            "notes": row[4] if len(row) > 4 else "",
        })
    return out


async def _collect_outages(memory: Any, start, end) -> list[dict]:
    from src.db.models import PowerOutage
    async with memory._engine.connect() as conn:
        rows = list(await conn.execute(
            select(PowerOutage)
            .where(PowerOutage.started_at >= start.isoformat())
            .where(PowerOutage.started_at < end.isoformat())
        ))
    return [
        {"start": r.started_at, "end": r.ended_at,
         "duration_min": r.duration_min}
        for r in rows
    ]


# ─── PDF rendering ──────────────────────────────────────────────────

def _register_fonts() -> tuple[str, str, str]:
    """Returns (text_font, bold_font, symbol_font) names registered."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    text_font = "Helvetica"
    bold_font = "Helvetica-Bold"
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(candidate):
            try:
                pdfmetrics.registerFont(TTFont("Cyr", candidate))
                text_font = "Cyr"
                bold = candidate.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
                if os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont("Cyr-Bold", bold))
                    bold_font = "Cyr-Bold"
                break
            except Exception:
                continue

    symbol_font = text_font
    for candidate in (
        # Symbola has the widest coverage of emoji (monochrome) — preferred
        "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
        "/usr/share/fonts/truetype/ancient-scripts/Symbola.ttf",
        "/usr/share/fonts/truetype/symbola/Symbola.ttf",
        "/usr/share/fonts/Symbola.ttf",
        # Noto symbols cover some, but not all emoji
        "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansSymbols-Regular.ttf",
        # Fallback to DejaVu (limited emoji)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(candidate):
            try:
                pdfmetrics.registerFont(TTFont("Sym", candidate))
                symbol_font = "Sym"
                log.info("chronicle_symbol_font_loaded", path=candidate)
                break
            except Exception:
                continue
    return text_font, bold_font, symbol_font


def _icon(symbol_font: str, char: str, size_pt: float = 14.0) -> str:
    """Render an emoji as an inline twemoji PNG (works for ALL emoji,
    not just the ones Symbola happens to ship). Symbola fallback path
    kept for graceful degradation if the PNG fetch is offline."""
    try:
        from src.integrations.emoji_inline import inline_emojis
        result = inline_emojis(char, size_pt=size_pt)
        if "<img" in result:
            return result
    except Exception:
        pass
    return f'<font name="{symbol_font}">{char}</font>'


def _safe_caption(text: str | None, size_pt: float = 12.0) -> str:
    """Replace every emoji in a free-form user caption with an inline PNG."""
    if not text:
        return ""
    try:
        from src.integrations.emoji_inline import inline_emojis
        return inline_emojis(text, size_pt=size_pt)
    except Exception:
        return text


def _render_pdf(
    week_number: int, start, end,
    embedded_photos: list[tuple[str, str, str]],
    total_photos: int,
    diary_stats: dict,
    feedings: list,
    achievements: list,
    vaccines: list,
    doctor_visits: list,
    growth: list,
    outages: list,
    nanny_note: str = "",
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, Image, KeepTogether, PageBreak, Paragraph,
            SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError:
        log.warning("chronicle_reportlab_missing")
        return b""

    text_font, bold_font, sym_font = _register_fonts()

    def _decorate(canvas, doc_):
        """Album style: cream background, double gold frame, corner dots, footer."""
        gold = colors.HexColor("#C9A961")
        cream = colors.HexColor("#FBF7F0")
        canvas.saveState()
        # Cream page background
        canvas.setFillColor(cream)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        # Outer gold frame
        canvas.setStrokeColor(gold)
        canvas.setLineWidth(0.6)
        canvas.rect(1.0 * cm, 1.0 * cm,
                    A4[0] - 2.0 * cm, A4[1] - 2.0 * cm)
        # Inner thinner frame
        canvas.setStrokeColor(colors.HexColor("#9E823F"))
        canvas.setLineWidth(0.2)
        canvas.rect(1.4 * cm, 1.4 * cm,
                    A4[0] - 2.8 * cm, A4[1] - 2.8 * cm)
        # Corner dots
        canvas.setFillColor(gold)
        for x, y in [
            (1.4 * cm, 1.4 * cm),
            (A4[0] - 1.4 * cm, 1.4 * cm),
            (1.4 * cm, A4[1] - 1.4 * cm),
            (A4[0] - 1.4 * cm, A4[1] - 1.4 * cm),
        ]:
            canvas.circle(x, y, 0.15 * cm, fill=1, stroke=0)
        # Footer
        canvas.setFont(text_font, 8)
        canvas.setFillColor(gold)
        canvas.drawCentredString(
            A4[0] / 2, 0.55 * cm,
            f"✦ Семейная хроника · неделя №{week_number} · {start.year} ✦",
        )
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.6 * cm, bottomMargin=1.6 * cm,
    )

    cover_style = ParagraphStyle(
        "Cover", fontName=bold_font, fontSize=26,
        alignment=1, leading=30, spaceAfter=2,
        textColor=colors.HexColor("#2D3748"),
    )
    week_style = ParagraphStyle(
        "Week", fontName=text_font, fontSize=15,
        alignment=1, spaceAfter=4,
        textColor=colors.HexColor("#3182CE"),
    )
    date_style = ParagraphStyle(
        "Date", fontName=text_font, fontSize=10,
        alignment=1, spaceAfter=12,
        textColor=colors.HexColor("#718096"),
    )
    h2_style = ParagraphStyle(
        "H2", fontName=bold_font, fontSize=14,
        textColor=colors.HexColor("#2C5282"),
        spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", fontName=text_font, fontSize=10.5, leading=15,
        textColor=colors.HexColor("#2D3748"),
    )
    sub_style = ParagraphStyle(
        "Sub", parent=body_style, fontSize=9.5, leading=13,
        textColor=colors.HexColor("#4A5568"), spaceAfter=4,
    )
    quote_style = ParagraphStyle(
        "Quote", fontName=text_font, fontSize=11, leading=16,
        leftIndent=10, rightIndent=10, spaceBefore=6, spaceAfter=2,
        textColor=colors.HexColor("#4A5568"),
        backColor=colors.HexColor("#EBF8FF"),
        borderPadding=8,
    )
    quote_attr_style = ParagraphStyle(
        "QuoteAttr", parent=body_style, fontSize=9,
        textColor=colors.HexColor("#718096"), alignment=2,
        spaceAfter=8,
    )

    flow = []

    # ─── Cover (compact) ───
    flow.append(Paragraph("Семейная хроника", cover_style))
    flow.append(Paragraph(f"Неделя №{week_number}", week_style))
    flow.append(Paragraph(
        f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}",
        date_style,
    ))
    flow.append(HRFlowable(
        width="50%", thickness=1, color=colors.HexColor("#CBD5E0"),
        spaceBefore=2, spaceAfter=8, hAlign="CENTER",
    ))

    # ─── Nanny note ───
    if nanny_note:
        flow.append(Paragraph(nanny_note, quote_style))
        flow.append(Paragraph("— Няня", quote_attr_style))

    # ─── Stats cards (only non-zero) ───
    cards = []
    def add(card_icon, label, value):
        cards.append([
            Paragraph(
                f'<para align="center">{_icon(sym_font, card_icon)}</para>',
                ParagraphStyle("Ic", fontName=text_font, fontSize=20,
                               alignment=1, leading=24),
            ),
            Paragraph(
                f'<para align="center"><font size="15" name="{bold_font}" color="#2D3748">{value}</font><br/>'
                f'<font size="9" color="#718096">{label}</font></para>',
                ParagraphStyle("V", fontName=text_font, alignment=1, leading=14),
            ),
        ])
    if diary_stats.get("feeds"):
        add("🍼", "кормлений", diary_stats["feeds"])
    if diary_stats.get("sleep_hours"):
        add("😴", "часов сна", f"~{diary_stats['sleep_hours']:.0f}")
    if diary_stats.get("diapers"):
        add("💧", "подгузников", diary_stats["diapers"])
    if total_photos:
        add("📸", "фото", total_photos)
    if feedings:
        add("🥄", "прикорма", len(feedings))
    if achievements:
        add("🌟", "достижений", len(achievements))
    if vaccines:
        add("💉", "прививок", len(vaccines))
    if doctor_visits:
        add("🩺", "визитов к врачу", len(doctor_visits))
    if growth:
        # Show latest weight/height in the cards
        latest = growth[-1]
        if latest.get("weight_g"):
            try:
                kg = float(latest["weight_g"]) / 1000.0
                add("⚖️", "вес", f"{kg:.2f} кг")
            except (TypeError, ValueError):
                pass
        if latest.get("height_cm"):
            add("📏", "рост", f"{latest['height_cm']} см")
    if outages:
        add("⚡", "отключений", len(outages))

    if cards:
        per_row = 4
        for i in range(0, len(cards), per_row):
            row = cards[i:i + per_row]
            while len(row) < per_row:
                row.append(["", ""])
            cell_tables = []
            for c in row:
                if isinstance(c[0], str):
                    cell_tables.append("")
                    continue
                nt = Table([[c[0]], [c[1]]], colWidths=[3.6 * cm],
                           style=TableStyle([
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 2),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ]))
                cell_tables.append(nt)
            t = Table([cell_tables], colWidths=[3.85 * cm] * per_row, hAlign="CENTER")
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
            ]))
            flow.append(t)
            flow.append(Spacer(1, 0.1 * cm))

    # ─── Photos (one per day, chronological) — directly on first page if fits ───
    if embedded_photos:
        flow.append(Paragraph(
            f"{_icon(sym_font, '📸')} Фото малыша", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=8,
        ))
        def _build_photo_table(item, *, hAlign: str = "CENTER"):
            """Build a single 8×8 cm photo cell with caption + monthly frame."""
            path, caption, when = item
            when_pretty = when
            is_monthly = False
            age_label = ""
            try:
                photo_dt = datetime.strptime(when, "%Y-%m-%d")
                when_pretty = photo_dt.strftime("%d.%m")
                if photo_dt.day == 2:
                    is_monthly = True
                    BABY_DOB = datetime(2025, 12, 2)
                    months = ((photo_dt.year - BABY_DOB.year) * 12 +
                              (photo_dt.month - BABY_DOB.month))
                    if months > 0:
                        if months < 12:
                            age_label = f"🎂 {months} МЕС"
                        elif months == 12:
                            age_label = "🎂 1 ГОД"
                        elif months % 12 == 0:
                            yrs = months // 12
                            age_label = (f"🎂 {yrs} ГОДА" if 2 <= yrs <= 4
                                         else f"🎂 {yrs} ЛЕТ")
                        else:
                            yrs = months // 12
                            rem = months % 12
                            yrs_word = ("ГОД" if yrs == 1
                                        else "ГОДА" if 2 <= yrs <= 4 else "ЛЕТ")
                            age_label = f"🎂 {yrs} {yrs_word} {rem} МЕС"
            except Exception:
                pass

            try:
                img = Image(path, width=8.0 * cm, height=8.0 * cm,
                            kind="proportional")
            except Exception:
                log.exception("photo_embed_failed", path=path)
                return None
            cap_lines = []
            if is_monthly and age_label:
                cap_lines.append(
                    f'<font name="{bold_font}" size="11" color="#C9A961">'
                    f'{age_label}</font>'
                )
            # User часто пишет в подписи дату-префикс типа «10.06», и она
            # дублируется с системной датой ниже. Срезаем ведущую DD.MM
            # (с годом или без) — оставляем только полезный текст.
            clean_caption = (caption or "").strip()
            clean_caption = _strip_leading_date(clean_caption)
            if clean_caption:
                cap_lines.append(
                    f'<font color="#2D3748" size="10">'
                    f'{_safe_caption(clean_caption, 11)}</font>'
                )
            cap_lines.append(
                f'<font color="#A0AEC0" size="8">{when_pretty}</font>'
            )
            cap_text = '<para align="center">' + "<br/>".join(cap_lines) + '</para>'
            frame_color = (colors.HexColor("#C9A961") if is_monthly
                           else colors.HexColor("#CBD5E0"))
            frame_width = 1.5 if is_monthly else 0.4
            style_rules = [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BOX", (0, 0), (-1, -1), frame_width, frame_color),
            ]
            if is_monthly:
                style_rules.append((
                    "BACKGROUND", (0, 1), (0, 1), colors.HexColor("#F0E4C4"),
                ))
            return Table(
                [[img], [Paragraph(cap_text, body_style)]],
                colWidths=[8.4 * cm], hAlign=hAlign,
                style=TableStyle(style_rules),
            )

        # Strict pagination per user request:
        #   Page 1: 2 фото (под статистикой)
        #   Page 2: 4 фото
        #   Page 3: 1 фото + дальше идут разделы
        page1 = embedded_photos[:2]
        page2 = embedded_photos[2:6]
        page3 = embedded_photos[6:7]
        extras = embedded_photos[7:]

        def _render_staircase(items, offset_cm: float = 5.5) -> None:
            """Render photos in pairs as a side-by-side staircase:
            left photo at the top of the row, right photo offset DOWN
            (offset_cm) so the pair forms the chess/zigzag shape.
            Odd trailing photo goes solo on the left."""
            pairs = []
            buf = []
            for it in items:
                if not it:
                    continue
                buf.append(it)
                if len(buf) == 2:
                    pairs.append(buf)
                    buf = []
            if buf:
                pairs.append(buf)

            for pair in pairs:
                if len(pair) == 2:
                    left = _build_photo_table(pair[0], hAlign="CENTER")
                    right = _build_photo_table(pair[1], hAlign="CENTER")
                    if left is None and right is None:
                        continue
                    right_stack = []
                    if right is not None:
                        right_stack.append(Spacer(1, offset_cm * cm))
                        right_stack.append(right)
                    grid = Table(
                        [[left or "", right_stack or ""]],
                        colWidths=[8.7 * cm, 8.7 * cm],
                    )
                    grid.setStyle(TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]))
                    flow.append(grid)
                else:
                    solo = _build_photo_table(pair[0], hAlign="LEFT")
                    if solo is not None:
                        flow.append(solo)

        # ─ Page 1: 2 photos, deep staircase offset (looks good with cover above) ─
        _render_staircase(page1, offset_cm=5.5)

        # ─ Page 2: 4 photos as 2 staircase pairs, tight offset so all fit ─
        if page2:
            flow.append(PageBreak())
            flow.append(Paragraph(
                f"{_icon(sym_font, '📸')} Фото малыша", h2_style,
            ))
            flow.append(HRFlowable(
                width="100%", thickness=0.5,
                color=colors.HexColor("#CBD5E0"), spaceAfter=8,
            ))
            _render_staircase(page2, offset_cm=2.5)

        # ─ Page 3: 1 photo solo on the left ─
        if page3:
            flow.append(PageBreak())
            flow.append(Paragraph(
                f"{_icon(sym_font, '📸')} Фото малыша", h2_style,
            ))
            flow.append(HRFlowable(
                width="100%", thickness=0.5,
                color=colors.HexColor("#CBD5E0"), spaceAfter=8,
            ))
            _render_staircase(page3, offset_cm=0.0)

        # ─ Overflow ─
        _render_staircase(extras, offset_cm=2.0)

    # ─── Достижения / Achievements ───
    if achievements:
        flow.append(Paragraph(
            f"{_icon(sym_font, '🌟')} Достижения Матвея", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=8,
        ))
        for a in achievements:
            head = (
                f'{_icon(sym_font, "◆")} '
                f'<font name="{bold_font}" color="#2C5282">{a.get("date", "")}</font>'
                f' — <font name="{bold_font}">{a.get("event", "?")}</font>'
            )
            if a.get("age"):
                head += f' <font color="#718096" size="9">({a["age"]})</font>'
            flow.append(Paragraph(head, body_style))
            if a.get("details"):
                flow.append(Paragraph(
                    f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<font color="#718096">{a["details"]}</font>',
                    sub_style,
                ))

    # ─── Прикорм ───
    if feedings:
        flow.append(Paragraph(
            f"{_icon(sym_font, '🥄')} Прикорм на этой неделе", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=8,
        ))
        for f in feedings:
            head = (
                f'{_icon(sym_font, "◆")} '
                f'<font name="{bold_font}" color="#2C5282">{f.get("date", "")}</font>'
                f' — <font name="{bold_font}">{f.get("product", "?")}</font>'
            )
            if f.get("portion"):
                head += f' <font color="#718096" size="9">({f["portion"]})</font>'
            flow.append(Paragraph(head, body_style))
            extras = []
            if f.get("reaction"):
                extras.append(f'<font color="#2F855A">реакция: {f["reaction"]}</font>')
            if f.get("details"):
                extras.append(f'<font color="#718096">{f["details"]}</font>')
            if extras:
                flow.append(Paragraph(
                    "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;" + " · ".join(extras),
                    sub_style,
                ))

    # ─── Прививки ───
    if vaccines:
        flow.append(Paragraph(
            f"{_icon(sym_font, '💉')} Прививки", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=8,
        ))
        for v in vaccines:
            when = v["when"][:10] if v.get("when") else ""
            title = (v.get("title", "") or "").lstrip("💉🩹").strip(" -—")
            flow.append(Paragraph(
                f'{_icon(sym_font, "◆")} '
                f'<font name="{bold_font}" color="#2C5282">{when}</font>'
                f' — <font name="{bold_font}">{title}</font>',
                body_style,
            ))

    # ─── Визиты к врачу ───
    if doctor_visits:
        flow.append(Paragraph(
            f"{_icon(sym_font, '🩺')} Визиты к врачу", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=8,
        ))
        for v in doctor_visits:
            head = (
                f'{_icon(sym_font, "◆")} '
                f'<font name="{bold_font}" color="#2C5282">{v.get("date", "")}</font>'
                f' — <font name="{bold_font}">{v.get("type", "")}</font>'
            )
            if v.get("doctor"):
                head += f' <font color="#4A5568">· {v["doctor"]}</font>'
            flow.append(Paragraph(head, body_style))
            extras = []
            if v.get("diagnosis"):
                extras.append(f'<font color="#2C5282">{v["diagnosis"]}</font>')
            if v.get("notes"):
                extras.append(f'<font color="#718096">{v["notes"]}</font>')
            if extras:
                flow.append(Paragraph(
                    "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;" + " · ".join(extras),
                    sub_style,
                ))

    # ─── Рост / вес ───
    if growth:
        flow.append(Paragraph(
            f"{_icon(sym_font, '📏')} Рост и вес", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=8,
        ))
        for g in growth:
            parts = []
            if g.get("weight_g"):
                try:
                    kg = float(g["weight_g"]) / 1000.0
                    parts.append(f'<font name="{bold_font}">⚖️ {kg:.2f} кг</font>')
                except (TypeError, ValueError):
                    parts.append(f'<font name="{bold_font}">⚖️ {g["weight_g"]}г</font>')
            if g.get("height_cm"):
                parts.append(f'<font name="{bold_font}">📐 {g["height_cm"]} см</font>')
            line = (
                f'{_icon(sym_font, "◆")} '
                f'<font name="{bold_font}" color="#2C5282">{g.get("date", "")}</font>'
                + (" — " + " · ".join(parts) if parts else "")
            )
            if g.get("age"):
                line += f' <font color="#718096" size="9">({g["age"]})</font>'
            flow.append(Paragraph(line, body_style))
            if g.get("notes"):
                flow.append(Paragraph(
                    f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<font color="#718096">{g["notes"]}</font>',
                    sub_style,
                ))

    # ─── Outages ───
    if outages:
        total_min = sum(o.get("duration_min") or 0 for o in outages)
        flow.append(Paragraph(
            f"{_icon(sym_font, '⚡')} Отключения света "
            f'<font size="10" color="#718096">— всего '
            f"{total_min // 60}ч {total_min % 60}мин</font>",
            h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=8,
        ))
        for o in outages[:10]:
            line = f"{_icon(sym_font, '◆')} {o['start'][:16].replace('T', ' ')}"
            if o.get("duration_min"):
                line += f" — {o['duration_min']} мин"
            flow.append(Paragraph(line, body_style))

    # ─── Компактная декоративная концовка ───
    # Single-line closer so it always fits at the end of the last content
    # page and doesn't create an empty trailing page.
    flow.append(Spacer(1, 0.4 * cm))
    closing_style = ParagraphStyle(
        "Closing", fontName=text_font, fontSize=10, leading=14,
        alignment=1, textColor=colors.HexColor("#718096"),
    )
    # Rotating closing epigraph — different one per week so the book
    # doesn't feel repetitive
    EPIGRAPHS = [
        ("Каждая неделя становится страницей.",
         "Каждая страница — частью книги.",
         "Каждая книга — частью жизни."),
        ("В каждом дне — маленькое чудо.",
         "В каждой неделе — большая история.",
         "Они складываются в детство."),
        ("Эти кадры мы будем пересматривать.",
         "Эти строки мы будем перечитывать.",
         "Эта неделя останется с нами навсегда."),
        ("Малыш растёт быстрее, чем нам кажется.",
         "Этот альбом — наша попытка остановить время.",
         "И запомнить каждую мелочь."),
        ("Сегодняшние пелёнки — завтрашние воспоминания.",
         "Сегодняшние слёзы — завтрашние улыбки.",
         "Спасибо, неделя, что ты была."),
        ("Дни летят, но мы их ловим.",
         "Каждый кадр — против забвения.",
         "Каждое слово — для будущего читателя."),
        ("Здесь жизнь идёт неспешно.",
         "Здесь каждый момент — это праздник.",
         "Здесь — мы вместе."),
        ("Эта неделя была доброй.",
         "Эта неделя была светлой.",
         "Эта неделя была нашей."),
        ("Не торопись, расти спокойно.",
         "Мы всё равно успеем всё запомнить.",
         "Каждое движение, каждый взгляд."),
        ("Маленькие победы. Большие открытия.",
         "Тёплые объятия. Сонное молочко.",
         "Из таких недель и состоит счастье."),
        ("Однажды Матвей откроет эту книгу.",
         "И увидит, как сильно его любили.",
         "С первой страницы."),
        ("Семь дней, семь фото, одна история.",
         "И эта история — наша.",
         "С любовью, всегда."),
        ("Время летит. Альбом растёт.",
         "Малыш меняется. Любовь — нет.",
         "Спасибо, что ты есть."),
    ]
    epigraph = EPIGRAPHS[week_number % len(EPIGRAPHS)]
    # Compose one line of joined text — fits anywhere
    joined = " ".join(epigraph)
    flow.append(Paragraph(
        f'<para align="center">'
        f'<font color="#C9A961" size="13">❦</font> '
        f'<i>{joined}</i> '
        f'<font color="#C9A961" size="13">❦</font></para>',
        closing_style,
    ))

    doc.build(flow, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


def register_chronicle_job(scheduler, memory, bot_manager, chat_id: int,
                           drive_client) -> None:
    # Tuesday is Матвей's day of week — he was born on Tue 02.12.2025.
    scheduler.add_job(
        generate_weekly_chronicle, "cron",
        day_of_week="tue", hour=20, minute=0, timezone="Europe/Kiev",
        args=[memory, bot_manager, chat_id, drive_client],
        id="weekly_chronicle", replace_existing=True,
    )
    log.info("chronicle_job_registered", day="tue")
