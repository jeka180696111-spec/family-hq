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
        feedings = await _collect_feedings(start, end)
        vaccines = await _collect_vaccines(start, end)
        outages = await _collect_outages(memory, start, end)

        # Download top 6 photos for embedding (3 rows x 2)
        embedded_photo_paths: list[tuple[str, str, str]] = []
        if drive_client and photos:
            for p in photos[:6]:
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

        # Generate warm narrative from Няня (LLM)
        nanny_note = await _nanny_weekly_note(
            diary_stats=diary_stats, photos=photos, feedings=feedings,
            week_number=week_number,
        )

        pdf_bytes = _render_pdf(
            week_number=week_number, start=start, end=end,
            embedded_photos=embedded_photo_paths,
            total_photos=len(photos),
            diary_stats=diary_stats,
            feedings=feedings,
            vaccines=vaccines,
            outages=outages,
            nanny_note=nanny_note,
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
                lines.append(f"📸 Фото: {len(photos)} (в PDF — топ 6)")
            if feedings:
                lines.append(f"🥄 Прикорма: {len(feedings)}")
            if vaccines:
                lines.append(f"💉 Прививок: {len(vaccines)}")
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


# ─── Nanny narrative (LLM) ──────────────────────────────────────────

async def _nanny_weekly_note(
    diary_stats: dict, photos: list, feedings: list, week_number: int,
) -> str:
    """Ask the LLM to write a warm 4-6 sentence weekly note from Няня."""
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
        ctx = (
            f"Неделя №{week_number}.\n"
            f"Кормлений (молоко/смесь): {diary_stats.get('feeds', 0)}\n"
            f"Сна всего: ~{diary_stats.get('sleep_hours', 0):.0f}ч\n"
            f"Подгузников: {diary_stats.get('diapers', 0)}\n"
            f"Фото сделано: {len(photos)}\n"
            f"Подписи к фото: {', '.join(captions[:8]) if captions else 'нет'}\n"
            f"Прикорм за неделю: {'; '.join(feed_lines) if feed_lines else 'не пробовал нового'}\n"
        )
        system = (
            "Ты — Няня, заботливая и тёплая. Сейчас сводка о неделе малыша "
            "Матвея в семейную хронику-альбом. Напиши 4-6 предложений на "
            "русском в формате тёплого письма для альбома. Без эмодзи, без "
            "хэштегов. Подчеркни 1-2 особенных момента из подписей к фото "
            "если есть. Тон: душевно, без официоза. НЕ выдумывай факты, "
            "опирайся только на данные."
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


async def _collect_feedings(start, end) -> list[dict]:
    """Read Прикорм sheet for entries this week.
    Columns: num, date, age, type, product, portion, reaction, details, author."""
    try:
        from src.config import get_settings
        from src.integrations.sheets import SheetsClient, _FEEDING_WORKSHEET
        s = get_settings()
        if not (s.google_service_account_json and s.sheet_baby_id):
            return []
        sheets = SheetsClient(s.google_service_account_json, s.sheet_baby_id, "")

        def _read_feeding():
            ws = sheets._gc.open_by_key(s.sheet_baby_id).worksheet(_FEEDING_WORKSHEET)
            return ws.get_all_values()
        # Ensure auth done
        if sheets._gc is None:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                s.google_service_account_json,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            sheets._gc = gspread.authorize(creds)
        try:
            all_rows = await sheets._run_sync(_read_feeding)
        except Exception:
            log.exception("chronicle_feedings_read_failed")
            return []
    except Exception:
        log.exception("chronicle_feedings_setup_failed")
        return []

    out = []
    for row in all_rows:
        if len(row) < 7:
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

def _register_fonts() -> tuple[str, str]:
    """Register Cyrillic body font + symbol font for emojis.
    Returns (text_font_name, symbol_font_name).
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    text_font = "Helvetica"
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(candidate):
            try:
                pdfmetrics.registerFont(TTFont("Cyr", candidate))
                text_font = "Cyr"
                # also bold variant
                bold = candidate.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
                if os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont("Cyr-Bold", bold))
                break
            except Exception:
                continue

    symbol_font = text_font
    for candidate in (
        "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
        "/usr/share/fonts/truetype/symbola/Symbola.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansSymbols-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    ):
        if os.path.exists(candidate):
            try:
                pdfmetrics.registerFont(TTFont("Sym", candidate))
                symbol_font = "Sym"
                break
            except Exception:
                continue

    return text_font, symbol_font


def _icon(symbol_font: str, char: str) -> str:
    """Inline-font-switched emoji for Paragraph (HTML markup)."""
    return f'<font name="{symbol_font}">{char}</font>'


def _render_pdf(week_number: int, start, end,
                embedded_photos: list[tuple[str, str, str]],
                total_photos: int,
                diary_stats: dict,
                feedings: list,
                vaccines: list,
                outages: list,
                nanny_note: str = "") -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, Image, KeepTogether, PageBreak, Paragraph,
            SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError:
        log.warning("chronicle_reportlab_missing")
        return b""

    text_font, sym_font = _register_fonts()
    bold_font = "Cyr-Bold" if text_font == "Cyr" else text_font

    # ── Decorative page border (drawn on every page) ──
    def _decorate(canvas, doc_):
        canvas.saveState()
        # outer thin border
        canvas.setStrokeColor(colors.HexColor("#C9D6E0"))
        canvas.setLineWidth(0.4)
        canvas.rect(1.2 * cm, 1.2 * cm,
                    A4[0] - 2.4 * cm, A4[1] - 2.4 * cm)
        # page footer
        canvas.setFont(text_font, 8)
        canvas.setFillColor(colors.HexColor("#A0AEC0"))
        canvas.drawCentredString(
            A4[0] / 2, 0.7 * cm,
            f"Семейная хроника · неделя №{week_number} · {start.year}",
        )
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2.5 * cm, bottomMargin=2.2 * cm,
    )

    cover_style = ParagraphStyle(
        "Cover", fontName=bold_font, fontSize=32,
        alignment=1, leading=38, spaceAfter=4,
        textColor=colors.HexColor("#2D3748"),
    )
    week_style = ParagraphStyle(
        "Week", fontName=text_font, fontSize=18,
        alignment=1, spaceAfter=10,
        textColor=colors.HexColor("#3182CE"),
    )
    date_style = ParagraphStyle(
        "Date", fontName=text_font, fontSize=11,
        alignment=1, spaceAfter=24,
        textColor=colors.HexColor("#718096"),
    )
    h2_style = ParagraphStyle(
        "H2", fontName=bold_font, fontSize=15,
        textColor=colors.HexColor("#2C5282"),
        spaceBefore=18, spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "Body", fontName=text_font, fontSize=10.5, leading=15,
        textColor=colors.HexColor("#2D3748"),
    )
    quote_style = ParagraphStyle(
        "Quote", fontName=text_font, fontSize=11, leading=17,
        leftIndent=14, rightIndent=14, spaceBefore=8, spaceAfter=8,
        textColor=colors.HexColor("#4A5568"),
        borderColor=colors.HexColor("#90CDF4"),
        borderWidth=0, borderPadding=10,
        backColor=colors.HexColor("#EBF8FF"),
    )
    quote_attr_style = ParagraphStyle(
        "QuoteAttr", parent=body_style, fontSize=9,
        textColor=colors.HexColor("#718096"), alignment=2,
        spaceAfter=10,
    )
    photo_caption_style = ParagraphStyle(
        "PhotoCap", fontName=text_font, fontSize=9, leading=12,
        alignment=1, textColor=colors.HexColor("#718096"), spaceAfter=10,
    )

    flow = []

    # ─── Cover ───
    flow.append(Spacer(1, 1 * cm))
    flow.append(Paragraph("Семейная хроника", cover_style))
    flow.append(Paragraph(f"Неделя №{week_number}", week_style))
    flow.append(Paragraph(
        f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}",
        date_style,
    ))
    flow.append(HRFlowable(
        width="60%", thickness=1, color=colors.HexColor("#CBD5E0"),
        spaceBefore=4, spaceAfter=14, hAlign="CENTER",
    ))

    # ─── Slovo Nyani — narrative block ───
    if nanny_note:
        flow.append(Paragraph(nanny_note, quote_style))
        flow.append(Paragraph("— Няня", quote_attr_style))
        flow.append(Spacer(1, 0.3 * cm))

    # ─── Stats cards ───
    cells = []

    def add(card_icon, label, value):
        cells.append([
            Paragraph(
                f'<para align="center">{_icon(sym_font, card_icon)}</para>',
                ParagraphStyle("Ic", fontName=text_font, fontSize=22,
                               alignment=1, leading=26),
            ),
            Paragraph(
                f'<para align="center"><font size="16" name="{bold_font}" color="#2D3748">{value}</font><br/>'
                f'<font size="9" color="#718096">{label}</font></para>',
                ParagraphStyle("V", fontName=text_font, alignment=1, leading=15),
            ),
        ])

    if diary_stats.get("feeds"):
        add("🍼", "кормлений", diary_stats["feeds"])
    if diary_stats.get("sleep_hours"):
        add("😴", "часов сна", f"~{diary_stats['sleep_hours']:.0f}")
    if diary_stats.get("diapers"):
        add("💧", "подгузников", diary_stats["diapers"])
    add("📸", "фото", total_photos)
    if feedings:
        add("🥄", "прикорма", len(feedings))
    if vaccines:
        add("💉", "прививок", len(vaccines))
    if outages:
        total_min = sum(o.get("duration_min") or 0 for o in outages)
        add("⚡", "отключений", f"{len(outages)}")

    # Lay out as 4 cards per row
    rows = []
    per_row = 4
    for i in range(0, len(cells), per_row):
        row = cells[i:i + per_row]
        # pad to per_row
        while len(row) < per_row:
            row.append(["", ""])
        # Flatten — each cell is icon over value
        cell_tables = []
        for c in row:
            nt = Table(
                [[c[0]], [c[1]]],
                colWidths=[3.8 * cm],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]),
            )
            cell_tables.append(nt)
        rows.append(cell_tables)
    if rows:
        for row in rows:
            t = Table([row], colWidths=[4.0 * cm] * per_row, hAlign="CENTER")
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
                ("LINEABOVE", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
            ]))
            flow.append(t)
            flow.append(Spacer(1, 0.1 * cm))
        flow.append(Spacer(1, 0.4 * cm))

    # ─── Photos ───
    if embedded_photos:
        flow.append(PageBreak())
        flow.append(Paragraph(
            f"{_icon(sym_font, '📸')} Фото малыша", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=10,
        ))

        photo_pairs = [(embedded_photos[i],
                        embedded_photos[i + 1] if i + 1 < len(embedded_photos) else None)
                       for i in range(0, len(embedded_photos), 2)]
        for pair in photo_pairs:
            row_cells = []
            for item in pair:
                if not item:
                    row_cells.append("")
                    continue
                path, caption, when = item
                try:
                    img = Image(path, width=7.5 * cm, height=7.5 * cm,
                                kind="proportional")
                    cap_text = (
                        f'<para align="center">'
                        f'<font color="#2D3748" size="10">{caption or "·"}</font><br/>'
                        f'<font color="#A0AEC0" size="8">{when}</font></para>'
                    )
                    nt = Table(
                        [[img], [Paragraph(cap_text, photo_caption_style)]],
                        colWidths=[7.8 * cm],
                        style=TableStyle([
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            # photo frame
                            ("BOX", (0, 0), (0, 0), 1.5, colors.white),
                            ("BACKGROUND", (0, 0), (0, 0), colors.white),
                            ("TOPPADDING", (0, 0), (0, 0), 6),
                            ("BOTTOMPADDING", (0, 0), (0, 0), 4),
                            ("LEFTPADDING", (0, 0), (0, 0), 6),
                            ("RIGHTPADDING", (0, 0), (0, 0), 6),
                            ("LINEBELOW", (0, 0), (0, 0), 1, colors.HexColor("#E2E8F0")),
                            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E0")),
                        ]),
                    )
                    row_cells.append(nt)
                except Exception:
                    log.exception("photo_embed_failed", path=path)
                    row_cells.append("")
            grid = Table([row_cells], colWidths=[8.4 * cm, 8.4 * cm],
                         hAlign="CENTER")
            grid.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            flow.append(grid)

    # ─── Прикорм (детально: продукт + реакция + детали) ───
    if feedings:
        flow.append(Paragraph(
            f"{_icon(sym_font, '🥄')} Прикорм на этой неделе", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=10,
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
                    ParagraphStyle(
                        "FeedSub", parent=body_style, fontSize=9.5,
                        leading=13, spaceAfter=4,
                    ),
                ))

    # ─── Прививки (детально: какая вакцина + дата) ───
    if vaccines:
        flow.append(Paragraph(
            f"{_icon(sym_font, '💉')} Прививки", h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=10,
        ))
        for v in vaccines:
            when = v["when"][:10] if v.get("when") else ""
            title = v.get("title", "")
            # Strip leading emoji for cleaner look since we render our own
            title_clean = title.lstrip("💉🩹").strip(" -—")
            line = (
                f'{_icon(sym_font, "◆")} '
                f'<font name="{bold_font}" color="#2C5282">{when}</font>'
                f' — <font name="{bold_font}">{title_clean}</font>'
            )
            flow.append(Paragraph(line, body_style))

    # ─── Outages ───
    if outages:
        total_min = sum(o.get("duration_min") or 0 for o in outages)
        flow.append(Paragraph(
            f"{_icon(sym_font, '⚡')} Отключения света "
            f"<font size=\"10\" color=\"#718096\">— всего "
            f"{total_min // 60}ч {total_min % 60}мин</font>",
            h2_style,
        ))
        flow.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#CBD5E0"), spaceAfter=10,
        ))
        for o in outages[:10]:
            line = f"{_icon(sym_font, '◆')} {o['start'][:16].replace('T', ' ')}"
            if o.get("duration_min"):
                line += f" — {o['duration_min']} мин"
            flow.append(Paragraph(line, body_style))

    # ─── Footer ───
    flow.append(Spacer(1, 1.0 * cm))
    footer = ParagraphStyle(
        "Foot", fontName=text_font, fontSize=8, alignment=1,
        textColor=colors.HexColor("#A0AEC0"),
    )
    flow.append(HRFlowable(
        width="40%", thickness=0.5,
        color=colors.HexColor("#E2E8F0"), spaceBefore=6,
        spaceAfter=8, hAlign="CENTER",
    ))
    flow.append(Paragraph(
        "Family HQ · автоматическая хроника", footer,
    ))

    doc.build(flow, onFirstPage=_decorate, onLaterPages=_decorate)
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
