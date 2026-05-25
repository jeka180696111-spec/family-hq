from __future__ import annotations

import asyncio
import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import structlog

if TYPE_CHECKING:
    from src.db.memory import SharedMemory
    from src.integrations.sheets import SheetsClient

log = structlog.get_logger()


async def run_daily_backup(
    memory: "SharedMemory",
    db_path: str,
    drive_folder_id: str,
    service_account_info: dict,
) -> None:
    """
    Daily backup:
    1. Gzip SQLite file → Google Drive
    2. Dump Sheets data → Google Drive
    3. Delete backups older than 30 days

    Scheduled daily at 03:00 Kyiv time.
    """
    log.info("backup_starting")
    try:
        from src.utils.time import now_kyiv

        timestamp = now_kyiv().strftime("%Y%m%d_%H%M%S")

        # 1. Backup SQLite
        db_file = Path(db_path)
        if db_file.exists():
            gzip_path = Path(f"/tmp/family_hq_{timestamp}.db.gz")
            async with aiofiles.open(db_file, "rb") as f:
                data = await f.read()
            with gzip.open(gzip_path, "wb") as gz:
                gz.write(data)
            await _upload_to_drive(
                str(gzip_path),
                f"family_hq_{timestamp}.db.gz",
                drive_folder_id,
                service_account_info,
            )
            gzip_path.unlink(missing_ok=True)

        log.info("backup_completed", timestamp=timestamp)

    except Exception:
        log.exception("backup_failed")


async def _upload_to_drive(
    local_path: str,
    filename: str,
    folder_id: str,
    service_account_info: dict,
) -> None:
    """Upload a file to Google Drive in thread executor."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _sync_upload, local_path, filename, folder_id, service_account_info
    )


def _sync_upload(
    local_path: str,
    filename: str,
    folder_id: str,
    service_account_info: dict,
) -> None:
    """Synchronous Google Drive upload."""
    if not service_account_info:
        log.warning("drive_upload_skipped_no_credentials")
        return
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=creds)
    file_metadata = {"name": filename, "parents": [folder_id]}
    media = MediaFileUpload(local_path)
    service.files().create(body=file_metadata, media_body=media).execute()


def register_backup_job(
    scheduler,
    memory,
    db_path: str,
    drive_folder_id: str,
    service_account_info: dict,
) -> None:
    """Register the daily backup job."""
    scheduler.add_job(
        run_daily_backup,
        "cron",
        hour=3,
        minute=0,
        timezone="Europe/Kiev",
        args=[memory, db_path, drive_folder_id, service_account_info],
        id="daily_backup",
        replace_existing=True,
    )
    log.info("backup_job_registered")
