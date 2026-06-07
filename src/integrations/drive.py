"""Generic Google Drive helper with folder auto-creation + caching."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

log = structlog.get_logger()


# list() supports both flags; create()/update() only support supportsAllDrives
_LIST_KW = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
_WRITE_KW = {"supportsAllDrives": True}


class DriveClient:
    def __init__(
        self, service_account_info: dict, root_folder_id: str,
        oauth_client_id: str = "", oauth_client_secret: str = "",
        oauth_refresh_token: str = "",
    ) -> None:
        self.sa = service_account_info
        self.root_id = root_folder_id
        self.oauth_client_id = oauth_client_id
        self.oauth_client_secret = oauth_client_secret
        self.oauth_refresh_token = oauth_refresh_token
        self._folder_cache: dict[tuple[str, str], str] = {}
        self._service = None

    @property
    def using_oauth(self) -> bool:
        return bool(
            self.oauth_client_id and self.oauth_client_secret and self.oauth_refresh_token
        )

    @classmethod
    def from_settings(cls, settings: Any) -> "DriveClient | None":
        sa = settings.google_service_account_json
        root = (getattr(settings, "drive_root_folder_id", "")
                or getattr(settings, "baby_photos_drive_folder_id", "")
                or settings.drive_backup_folder_id)
        if not root:
            return None
        oauth_id = getattr(settings, "google_oauth_client_id", "")
        oauth_secret = getattr(settings, "google_oauth_client_secret", "")
        oauth_token = getattr(settings, "google_oauth_refresh_token", "")
        if not sa and not (oauth_id and oauth_secret and oauth_token):
            return None
        return cls(sa or {}, root, oauth_id, oauth_secret, oauth_token)

    def _build(self):
        if self._service is not None:
            return self._service
        from googleapiclient.discovery import build
        if self.using_oauth:
            from google.oauth2.credentials import Credentials as UserCredentials
            creds = UserCredentials(
                token=None,
                refresh_token=self.oauth_refresh_token,
                client_id=self.oauth_client_id,
                client_secret=self.oauth_client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=["https://www.googleapis.com/auth/drive"],
            )
            log.info("drive_client_oauth_mode")
        else:
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                self.sa, scopes=["https://www.googleapis.com/auth/drive"],
            )
            log.info("drive_client_sa_mode")
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    async def ensure_folder(self, name: str, parent_id: str | None = None) -> str:
        parent = parent_id or self.root_id
        key = (parent, name)
        if key in self._folder_cache:
            return self._folder_cache[key]
        loop = asyncio.get_event_loop()
        folder_id = await loop.run_in_executor(None, self._find_or_create_folder, name, parent)
        self._folder_cache[key] = folder_id
        return folder_id

    def _find_or_create_folder(self, name: str, parent: str) -> str:
        svc = self._build()
        safe_name = name.replace("'", "\\'")
        q = (
            f"mimeType='application/vnd.google-apps.folder' "
            f"and name='{safe_name}' and '{parent}' in parents and trashed=false"
        )
        res = svc.files().list(
            q=q, fields="files(id,name)", pageSize=10,
            corpora="allDrives", **_LIST_KW,
        ).execute()
        files = res.get("files", []) or []
        if files:
            return files[0]["id"]
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        f = svc.files().create(body=meta, fields="id", **_WRITE_KW).execute()
        log.info("drive_folder_created", name=name, parent=parent, id=f["id"])
        return f["id"]

    async def ensure_path(self, parts: list[str]) -> str:
        current = self.root_id
        for p in parts:
            current = await self.ensure_folder(p, current)
        return current

    async def upload(
        self, local_path: str, filename: str, folder_id: str,
        description: str | None = None,
    ) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._upload_sync, local_path, filename, folder_id, description,
        )

    def _upload_sync(self, local_path: str, filename: str, folder_id: str, description: str | None) -> dict:
        from googleapiclient.http import MediaFileUpload
        if not os.path.exists(local_path):
            raise RuntimeError(f"local file missing: {local_path}")
        size = os.path.getsize(local_path)
        if size == 0:
            raise RuntimeError(f"local file is empty (0 bytes): {local_path}")
        svc = self._build()
        meta: dict[str, Any] = {"name": filename, "parents": [folder_id]}
        if description:
            meta["description"] = description
        media = MediaFileUpload(local_path, resumable=False)
        try:
            f = svc.files().create(
                body=meta, media_body=media, fields="id,webViewLink", **_WRITE_KW,
            ).execute()
        except Exception as e:
            err_text = str(e)
            log.exception(
                "drive_upload_failed",
                local=local_path, name=filename, folder=folder_id,
                size=size, error=err_text[:300],
            )
            # Detect the well-known SA-no-storage error and re-raise with a clearer message
            if ("storageQuotaExceeded" in err_text
                    or "Service Accounts do not have storage quota" in err_text
                    or "quota" in err_text.lower()):
                raise RuntimeError(
                    "Service Account не может загружать файлы в личный Google Drive "
                    "(нет своего storage quota). Решения: 1) использовать Shared Drive "
                    "(только Google Workspace), 2) переключить архив фото в Telegram-канал, "
                    "3) подключить OAuth refresh token владельца. "
                    f"Исходная ошибка: {err_text[:150]}"
                )
            raise
        log.info(
            "drive_uploaded", name=filename, folder=folder_id,
            file_id=f.get("id"), size=size,
        )
        return {"id": f.get("id"), "url": f.get("webViewLink")}
