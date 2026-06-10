"""Baby photo memory: archive Telegram photos of Матвей to Google Drive
in a sane folder tree (Матвей/2026-06/) with auto-computed age + caption.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import structlog

from src.utils.time import KYIV_TZ, iso_now, now_kyiv

log = structlog.get_logger()


BABY_DOB = datetime(2025, 12, 2, 10, 0, tzinfo=KYIV_TZ)


def _age_label(dob: datetime, when: datetime) -> str:
    total_months = (when.year - dob.year) * 12 + (when.month - dob.month)
    if when.day < dob.day:
        total_months -= 1
    if total_months <= 0:
        days = max(0, (when.date() - dob.date()).days)
        return f"{days} дн"
    years, months = divmod(total_months, 12)
    if years == 0:
        return f"{months} мес"
    if months == 0:
        return f"{years} г"
    return f"{years} г {months} мес"


async def archive_photo(
    local_path: str,
    caption: str,
    drive_client: Any,
    memory: Any,
) -> dict:
    """Upload to Drive (Матвей/YYYY-MM/) + persist record. Returns details.

    Date for archival is parsed from the caption first (so retroactive
    uploads — 'роддом', '2 мес', '02.12.2025' — land in the right month
    folder with the correct age label). Falls back to now if caption has
    no recognisable date.
    """
    from src.integrations.caption_parser import parse_caption_date
    captured = parse_caption_date(caption) or now_kyiv()
    age = _age_label(BABY_DOB, captured)
    when_for_folder = captured  # year-month folder follows the captured date
    when_now = now_kyiv()  # used for the upload timestamp prefix in filename
    safe_caption = (caption or "").strip()[:120]
    ext = os.path.splitext(local_path)[1] or ".jpg"
    drive_name = (
        f"{captured.strftime('%Y-%m-%d')}_Matvey_{age.replace(' ', '')}"
        f"_{safe_caption[:40] or 'foto'}{ext}"
    )
    drive_file_id = None
    drive_url = None
    upload_error = None

    if drive_client:
        try:
            folder_id = await drive_client.ensure_path([
                "👶 Матвей · Фото",
                captured.strftime("%Y-%m"),
            ])
            result = await drive_client.upload(
                local_path, drive_name, folder_id,
                description=f"Возраст: {age}\n{safe_caption}",
            )
            drive_file_id = result.get("id")
            drive_url = result.get("url")
            log.info("baby_photo_drive_uploaded", file_id=drive_file_id, age=age)
        except Exception as e:
            log.exception("baby_photo_drive_upload_failed")
            upload_error = str(e)[:200]
    else:
        log.info("baby_photo_drive_skipped_no_client")
        upload_error = "drive_not_configured"

    # Persist record. created_at = the *captured* date (from the
    # caption or today) so chronicle queries by date find photos on
    # the day they DEPICT, not the day they were uploaded.
    db_id = None
    try:
        from sqlalchemy import insert
        from src.db.models import BabyPhoto
        async with memory._engine.begin() as conn:
            res = await conn.execute(insert(BabyPhoto).values(
                local_path=local_path,
                drive_file_id=drive_file_id,
                caption=safe_caption or None,
                age_label=age,
                tags=f"baby,matvey,{age},{captured.strftime('%Y-%m')}",
                created_at=captured.isoformat(),
            ))
            db_id = res.inserted_primary_key[0] if res.inserted_primary_key else None
    except Exception:
        log.exception("baby_photo_db_save_failed")

    return {
        "age": age,
        "drive_id": drive_file_id,
        "drive_url": drive_url,
        "db_id": db_id,
        "drive_name": drive_name,
        "error": upload_error,
    }
