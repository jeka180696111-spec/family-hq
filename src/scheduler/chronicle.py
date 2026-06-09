"""Weekly Family Chronicle PDF — substantial recap of the past 7 days.

Contains:
  - Cover with week number + range
  - Top 4 embedded photos of Матвей from Drive
  - Baby diary stats: sleep total, feeds, diapers
  - Milestones (Достижения sheet)
  - Vaccines done / coming up
  - Trips
  - Power outages summary
  - Notable events

Saved to Google Drive '📖 Хроника семьи / <year> / Тиждень NN.pdf'.
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


async def generate_weekly_chronicle(memory: Any, bot_manager: Any, chat_id: int,
                                    drive_client: Any) -> None:
    try:
        from src.utils.time import now_kyiv
        end = now_kyiv()
        start = end - timedelta(days=7)
        week_number = end.isocalendar()[1]

        photos = await _collect_photos(memory, start, end)
        diary_stats = await _collect_diary_stats(start, end)
        milestones = await _collect_milestones(start, end)
        vaccines = await _collect_vaccines(start, end)
        trips = await _collect_trips(memory, start, end)
        outages = await _collect_outages(memory, start, end)

        # Download top photos for embedding
        embedded_photo_paths: list[tuple[str, str, str]] = []
        if drive_client and photos:
            for p in photos[:4]:
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

        pdf_bytes = _render_pdf(
            week_number=week_number, start=start, end=end,
            embedded_photos=embedded_photo_paths,
            total_photos=len(photos),
            diary_stats=diary_stats,
            milestones=milestones,
            vaccines=vaccines,
            trips=trips,
            outages=outages,
        )

        # Cleanup temp files
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
                "",
            ]
            if diary_stats.get("feeds"):
                lines.append(f"🍼 Кормлений: {diary_stats['feeds']}")
            if diary_stats.get("sleep_hours"):
                lines.append(f"😴 Сна всего: ~{diary_stats['sleep_hours']:.0f}ч")
            if diary_stats.get("diapers"):
                lines.append(f"💧 Подгузников: {diary_stats['diapers']}")
            if photos:
                lines.append(f"📸 Фото: {len(photos)} (в PDF — топ 4)")
            if milestones:
                lines.append(f"⭐ Вех: {len(milestones)}")
            if vaccines:
                lines.append(f"💉 Прививок: {len(vaccines)}")
            if trips:
                lines.append(f"🚗 Поездок: {len(trips)}")
            if outages:
                total_min = sum(o.get("duration_min") or 0 for o in outages)
                lines.append(
                    f"⚡ Отключений: {len(outages)} (всего {total_min // 60}ч {total_min % 60}мин)"
                )
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


# ─── Data collectors ────────────────────────────────────────────────

async def _collect_photos(memory: Any, start, end) -> list[dict]:
    from src.db.models import BabyPhoto
    async with memory._engine.connect() as conn:
        rows = list(await conn.execute(
            select(BabyPhoto)
            .where(BabyPhoto.created_at >= start.isoformat())
            .where(BabyPhoto.created_at < end.isoformat())
            .order_by(BabyPhoto.id.desc())
        ))
    return [
        {"caption": r.caption or "", "age": r.age_label,
         "drive_id": r.drive_file_id, "when": r.created_at}
        for r in rows
    ]


async def _collect_diary_stats(start, end) -> dict:
    """Read Дневник sheet and aggregate sleep / food / diapers."""
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
        # Compare naively (sheet is Kyiv-local, start/end are too)
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

    # Approximate sleep hours: count "уснул→проснулся" pairs
    sleep_hours = 0.0
    last_sleep_start: datetime | None = None
    for dt, event in sorted(sleep_segments):
        if any(w in event for w in ("уснул", "лёг", "лег", "начал спать")):
            last_sleep_start = dt
        elif any(w in event for w in ("проснул", "встал", "разбудил")) and last_sleep_start:
            delta = (dt - last_sleep_start).total_seconds() / 3600
            if 0 < delta < 14:  # sanity bounds
                sleep_hours += delta
            last_sleep_start = None

    return {
        "feeds": feeds,
        "diapers": diapers,
        "sleep_hours": sleep_hours,
        "diary_entries": len(rows),
    }


async def _collect_milestones(start, end) -> list[dict]:
    """Read Достижения sheet for entries this week."""
    try:
        from src.config import get_settings
        from src.integrations.sheets import SheetsClient
        s = get_settings()
        if not (s.google_service_account_json and s.sheet_baby_id):
            return []
        sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")
        try:
            # Try via get_baby_diary with kind=milestone if available;
            # otherwise read 'Достижения' worksheet directly.
            rows = await sheets.get_baby_diary(days=10, kind="milestone")
        except Exception:
            rows = []
    except Exception:
        log.exception("chronicle_milestones_failed")
        return []
    out = []
    for r in rows[:20]:
        d = r.data
        out.append({
            "date": d.get("date", ""),
            "event": d.get("event", ""),
            "details": d.get("notes", ""),
        })
    return out


async def _collect_vaccines(start, end) -> list[dict]:
    """Pull vaccine events from Google Calendar that fall in the week."""
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


async def _collect_trips(memory: Any, start, end) -> list[dict]:
    from src.db.models import Trip
    async with memory._engine.connect() as conn:
        rows = list(await conn.execute(
            select(Trip)
            .where(Trip.depart_at >= start.isoformat())
            .where(Trip.depart_at < end.isoformat())
        ))
    return [
        {"origin": r.origin, "destination": r.destination,
         "depart_at": r.depart_at, "distance_km": r.distance_km,
         "fuel_l": r.fuel_estimate_l}
        for r in rows
    ]


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


# ─── PDF renderer ───────────────────────────────────────────────────

def _render_pdf(week_number: int, start, end,
                embedded_photos: list[tuple[str, str, str]],
                total_photos: int,
                diary_stats: dict,
                milestones: list,
                vaccines: list,
                trips: list,
                outages: list) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            Image, PageBreak, Paragraph, SimpleDocTemplate,
            Spacer, Table, TableStyle,
        )
    except ImportError:
        log.warning("chronicle_reportlab_missing")
        return b""

    font_name = "Helvetica"
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/DejaVuSans.ttf",
    ):
        try:
            if os.path.exists(candidate):
                pdfmetrics.registerFont(TTFont("Cyr", candidate))
                font_name = "Cyr"
                break
        except Exception:
            continue

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Title"], fontName=font_name,
        fontSize=22, alignment=1, spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["BodyText"], fontName=font_name,
        fontSize=11, alignment=1, textColor=colors.grey, spaceAfter=20,
    )
    h2_style = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontName=font_name,
        fontSize=14, textColor=colors.HexColor("#2E5894"),
        spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontName=font_name,
        fontSize=10, leading=14,
    )
    photo_caption_style = ParagraphStyle(
        "PhotoCap", parent=body_style, fontSize=9,
        alignment=1, textColor=colors.grey, spaceAfter=12,
    )

    flow = []

    # ── Cover ──
    flow.append(Paragraph("📖 Семейная хроника", title_style))
    flow.append(Paragraph(f"Неделя №{week_number}", title_style))
    flow.append(Paragraph(
        f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}",
        subtitle_style,
    ))

    # ── Stats summary table ──
    summary = []
    if diary_stats.get("feeds"):
        summary.append(["🍼 Кормлений", str(diary_stats["feeds"])])
    if diary_stats.get("sleep_hours"):
        summary.append(["😴 Сна всего", f"~{diary_stats['sleep_hours']:.0f} часов"])
    if diary_stats.get("diapers"):
        summary.append(["💧 Подгузников", str(diary_stats["diapers"])])
    summary.append(["📸 Фото", str(total_photos)])
    summary.append(["⭐ Вех", str(len(milestones))])
    summary.append(["💉 Прививок", str(len(vaccines))])
    summary.append(["🚗 Поездок", str(len(trips))])
    if outages:
        total_min = sum(o.get("duration_min") or 0 for o in outages)
        summary.append([
            "⚡ Отключений",
            f"{len(outages)} (всего {total_min // 60}ч {total_min % 60}мин)",
        ])
    if summary:
        t = Table(summary, colWidths=[6 * cm, 8 * cm], hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), font_name, 11),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F0F4F8")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D8E0")),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 0.4 * cm))

    # ── Photos ──
    if embedded_photos:
        flow.append(Paragraph("Фото малыша за неделю", h2_style))
        photo_pairs = [(embedded_photos[i], embedded_photos[i + 1] if i + 1 < len(embedded_photos) else None)
                       for i in range(0, len(embedded_photos), 2)]
        for pair in photo_pairs:
            cells = []
            for item in pair:
                if not item:
                    cells.append("")
                    continue
                path, caption, when = item
                try:
                    img = Image(path, width=7.5 * cm, height=7.5 * cm,
                                kind="proportional")
                    cap = f"{when}<br/>{caption}" if caption else when
                    cells.append([img, Paragraph(cap, photo_caption_style)])
                except Exception:
                    cells.append("")
            if cells:
                row = []
                for c in cells:
                    if isinstance(c, list):
                        # Use a nested table for image + caption
                        nt = Table([[c[0]], [c[1]]], colWidths=[7.5 * cm])
                        nt.setStyle(TableStyle([
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]))
                        row.append(nt)
                    else:
                        row.append(c)
                grid = Table([row], colWidths=[8 * cm, 8 * cm], hAlign="CENTER")
                grid.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]))
                flow.append(grid)
                flow.append(Spacer(1, 0.3 * cm))
        flow.append(Spacer(1, 0.3 * cm))

    # ── Milestones ──
    if milestones:
        flow.append(Paragraph(f"⭐ Вехи Матвея ({len(milestones)})", h2_style))
        for m in milestones[:10]:
            line = f"• <b>{m.get('date', '')}</b> — {m.get('event', '')}"
            if m.get("details"):
                line += f" ({m['details']})"
            flow.append(Paragraph(line, body_style))

    # ── Vaccines ──
    if vaccines:
        flow.append(Paragraph(f"💉 Прививки ({len(vaccines)})", h2_style))
        for v in vaccines:
            when = v["when"][:10] if v.get("when") else ""
            flow.append(Paragraph(
                f"• <b>{when}</b> — {v.get('title', '')}", body_style,
            ))

    # ── Trips ──
    if trips:
        flow.append(Paragraph(f"🚗 Поездки ({len(trips)})", h2_style))
        for t in trips:
            flow.append(Paragraph(
                f"• {t['depart_at'][:10]} · <b>{t['origin']} → {t['destination']}</b>"
                f" · {t.get('distance_km', '?')} км · ~{t.get('fuel_l', '?')} л",
                body_style,
            ))

    # ── Outages ──
    if outages:
        total_min = sum(o.get("duration_min") or 0 for o in outages)
        flow.append(Paragraph(
            f"⚡ Отключения света ({len(outages)} · {total_min // 60}ч {total_min % 60}мин)",
            h2_style,
        ))
        for o in outages[:10]:
            line = f"• {o['start'][:16].replace('T', ' ')}"
            if o.get("duration_min"):
                line += f" — {o['duration_min']} мин"
            flow.append(Paragraph(line, body_style))

    flow.append(Spacer(1, 1.5 * cm))
    footer_style = ParagraphStyle(
        "Footer", parent=body_style, fontSize=8,
        alignment=1, textColor=colors.grey,
    )
    flow.append(Paragraph(
        "📖 Family HQ · автоматическая хроника каждое воскресенье",
        footer_style,
    ))
    doc.build(flow)
    return buf.getvalue()


def register_chronicle_job(scheduler, memory, bot_manager, chat_id: int,
                           drive_client) -> None:
    scheduler.add_job(
        generate_weekly_chronicle, "cron",
        day_of_week="sun", hour=20, minute=0, timezone="Europe/Kiev",
        args=[memory, bot_manager, chat_id, drive_client],
        id="weekly_chronicle", replace_existing=True,
    )
    log.info("chronicle_job_registered")
