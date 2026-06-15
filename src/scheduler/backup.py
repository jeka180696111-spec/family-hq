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


_BACKUP_SUBFOLDER = "🗄 БД-бэкапы"


async def _upload_to_drive(
    local_path: str,
    filename: str,
    folder_id: str,
    service_account_info: dict,
) -> None:
    """Upload a file to Google Drive via the shared DriveClient.

    The .db.gz dumps land in a dedicated subfolder so the main backup
    root stays clean for human-readable items (photos, chronicles).

    Picks OAuth when configured (fixes the personal-Gmail 'SA has no
    quota' bug), falls back to Service Account otherwise.
    """
    from src.config import get_settings
    from src.integrations.drive import DriveClient
    settings = get_settings()
    client = DriveClient(
        service_account_info or {},
        folder_id,
        oauth_client_id=getattr(settings, "google_oauth_client_id", ""),
        oauth_client_secret=getattr(settings, "google_oauth_client_secret", ""),
        oauth_refresh_token=getattr(settings, "google_oauth_refresh_token", ""),
    )
    if not (service_account_info or client.using_oauth):
        log.warning("drive_upload_skipped_no_credentials")
        return
    target_folder = await client.ensure_folder(_BACKUP_SUBFOLDER, parent_id=folder_id)
    await client.upload(local_path, filename, target_folder)


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
