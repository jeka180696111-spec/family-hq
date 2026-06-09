"""Weekly Family Chronicle — every Sunday 20:00 generates a PDF that
captures the past 7 days of the family's life:

  - top photos of Матвей from the diary period
  - milestones the baby hit this week
  - trips that happened or were planned
  - notable events from the chat (alerts, outages, household)
  - a fun line: longest sleep, most active day, etc.

Saved to Google Drive under '📖 Хроника · YYYY/Тиждень NN.pdf' and
linked in the family chat. Over time it becomes a year-by-year book.
"""
from __future__ import annotations

import io
import os
import tempfile
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

        # Gather sections
        photos = await _collect_photos(memory, start, end)
        trips = await _collect_trips(memory, start, end)
        outages = await _collect_outages(memory, start, end)
        events = await _collect_event_log(memory, start, end)

        pdf_bytes = _render_pdf(
            week_number=week_number, start=start, end=end,
            photos=photos, trips=trips, outages=outages, events=events,
        )
        if not pdf_bytes:
            log.info("chronicle_empty_week")
            return

        # Upload to Drive
        filename = f"Тиждень_{week_number:02d}_{start.strftime('%Y-%m-%d')}.pdf"
        drive_url = None
        if drive_client:
            try:
                folder_id = await drive_client.ensure_path([
                    "📖 Хроника", str(end.year),
                ])
                with tempfile.NamedTemporaryFile(
                        suffix=".pdf", delete=False) as tmp:
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
            text_lines = [
                f"📖 <b>Семейная хроника · неделя №{week_number}</b>",
                f"📅 {start.strftime('%d.%m')} — {end.strftime('%d.%m.%Y')}",
            ]
            if photos:
                text_lines.append(f"📸 Фото: {len(photos)}")
            if trips:
                text_lines.append(f"🚗 Поездки: {len(trips)}")
            if outages:
                total_min = sum(o.get("duration_min") or 0 for o in outages)
                text_lines.append(
                    f"⚡ Отключений: {len(outages)} · в сумме {total_min // 60}ч {total_min % 60}мин"
                )
            if drive_url:
                text_lines.append(f"\n📂 PDF: {drive_url}")
            else:
                text_lines.append("\n⚠️ PDF не сохранён в Drive (нет настройки)")
            try:
                await bot_manager.send_message(
                    agent_id="devops", chat_id=chat_id,
                    text="\n".join(text_lines),
                )
            except Exception:
                log.exception("chronicle_announce_failed")
        log.info("chronicle_done", week=week_number, photos=len(photos))
    except Exception:
        log.exception("chronicle_failed")


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


async def _collect_event_log(memory: Any, start, end) -> list[dict]:
    from src.db.models import EventLog
    async with memory._engine.connect() as conn:
        rows = list(await conn.execute(
            select(EventLog)
            .where(EventLog.created_at >= start.isoformat())
            .where(EventLog.created_at < end.isoformat())
            .where(EventLog.level.in_(("INFO", "WARNING")))
        ))
    return [{"event": r.event, "created_at": r.created_at} for r in rows[:30]]


def _render_pdf(week_number: int, start, end, photos: list,
                trips: list, outages: list, events: list) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError:
        log.warning("chronicle_reportlab_missing")
        return b""

    # Register a Unicode font so Cyrillic renders
    font_name = "Helvetica"
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
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
    title = styles["Title"]
    title.fontName = font_name
    h2 = styles["Heading2"]
    h2.fontName = font_name
    body = styles["BodyText"]
    body.fontName = font_name

    flow = []
    flow.append(Paragraph(f"Семейная хроника · неделя №{week_number}", title))
    flow.append(Paragraph(
        f"{start.strftime('%d %B %Y')} — {end.strftime('%d %B %Y')}", body,
    ))
    flow.append(Spacer(1, 0.5 * cm))

    if photos:
        flow.append(Paragraph(f"Фото малыша ({len(photos)})", h2))
        for p in photos[:15]:
            line = f"• {p['when'][:10]} · {p['age']}"
            if p.get("caption"):
                line += f" — {p['caption']}"
            flow.append(Paragraph(line, body))
        flow.append(Spacer(1, 0.3 * cm))

    if trips:
        flow.append(Paragraph(f"Поездки ({len(trips)})", h2))
        for t in trips:
            flow.append(Paragraph(
                f"• {t['depart_at'][:10]} · {t['origin']} → {t['destination']} · "
                f"{t.get('distance_km', '?')} км · "
                f"~{t.get('fuel_l', '?')} л топлива",
                body,
            ))
        flow.append(Spacer(1, 0.3 * cm))

    if outages:
        total_min = sum(o.get("duration_min") or 0 for o in outages)
        flow.append(Paragraph(
            f"Отключения света ({len(outages)} · в сумме "
            f"{total_min // 60}ч {total_min % 60}мин)", h2,
        ))
        for o in outages[:10]:
            line = f"• {o['start'][:16].replace('T', ' ')}"
            if o.get("duration_min"):
                line += f" — {o['duration_min']} мин"
            flow.append(Paragraph(line, body))
        flow.append(Spacer(1, 0.3 * cm))

    if events:
        flow.append(Paragraph(f"Заметки ({len(events)})", h2))
        for e in events[:12]:
            flow.append(Paragraph(
                f"• {e['created_at'][:16].replace('T', ' ')} — {e['event']}",
                body,
            ))

    flow.append(Spacer(1, 1 * cm))
    flow.append(Paragraph(
        "📖 Family HQ · автоматически сохраняется каждое воскресенье",
        body,
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
