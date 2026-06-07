"""Baby photo memory: archive Telegram photos of Матвей to Google Drive
with auto-computed age + caption, plus DB record for retrieval.

Designed for the grandmas digest later: pull "last 7 days, 3 photos"
without manual tagging.
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
    service_account_info: dict | None,
    drive_folder_id: str | None,
    memory: Any,
) -> dict:
    """Upload to Drive (if configured) + store record. Returns {age, drive_id?, db_id}."""
    when = now_kyiv()
    age = _age_label(BABY_DOB, when)
    safe_caption = (caption or "").strip()[:120]
    ext = os.path.splitext(local_path)[1] or ".jpg"
    drive_name = f"{when.strftime('%Y-%m-%d')}_Matvey_{age.replace(' ', '')}_{safe_caption[:40] or 'foto'}{ext}"
    drive_file_id = None

    if service_account_info and drive_folder_id:
        try:
            import asyncio
            drive_file_id = await asyncio.get_event_loop().run_in_executor(
                None, _upload_to_drive,
                local_path, drive_name, drive_folder_id, service_account_info,
            )
        except Exception:
            log.exception("baby_photo_drive_upload_failed")

    # Persist record
    try:
        from sqlalchemy import insert
        from src.db.models import BabyPhoto
        async with memory._engine.begin() as conn:
            res = await conn.execute(insert(BabyPhoto).values(
                local_path=local_path,
                drive_file_id=drive_file_id,
                caption=safe_caption or None,
                age_label=age,
                tags=f"baby,matvey,{age},{when.strftime('%Y-%m')}",
                created_at=iso_now(),
            ))
            db_id = res.inserted_primary_key[0] if res.inserted_primary_key else None
    except Exception:
        log.exception("baby_photo_db_save_failed")
        db_id = None

    return {"age": age, "drive_id": drive_file_id, "db_id": db_id, "drive_name": drive_name}


def _upload_to_drive(local_path: str, name: str, folder_id: str, sa_info: dict) -> str:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=creds)
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaFileUpload(local_path)
    f = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return f.get("id")
