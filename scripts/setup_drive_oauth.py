"""One-time OAuth setup for Google Drive uploads under YOUR Gmail quota.

Run once on your laptop:
    python scripts/setup_drive_oauth.py

It opens a browser, you log in with your Gmail, grant Drive access,
and the script prints three values to paste into Railway env:
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET
    GOOGLE_OAUTH_REFRESH_TOKEN

After this, photos and other agent uploads land in YOUR Drive (15 GB
free Gmail quota) instead of failing on the service-account 0-quota.

Prerequisites:
  1. https://console.cloud.google.com → APIs & Services → Credentials
  2. + CREATE CREDENTIALS → OAuth client ID
  3. Application type: 'Desktop app' (NOT web app)
  4. Download the JSON file → save as client_secret.json next to this script
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive"]


def main() -> None:
    here = Path(__file__).parent
    secret_path = here / "client_secret.json"
    if not secret_path.exists():
        print(f"❌ Не нашёл {secret_path}")
        print("Скачай 'OAuth client ID' (Desktop app) JSON из Google Cloud Console")
        print(f"и сохрани его как {secret_path}")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌ Установи зависимости: pip install google-auth-oauthlib")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    print("🌐 Сейчас откроется браузер. Войди под своим Gmail и разреши доступ.")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print("❌ Refresh token не получен. Удали разрешение в "
              "https://myaccount.google.com/permissions и попробуй снова.")
        sys.exit(1)

    info = json.loads(secret_path.read_text())
    client_info = info.get("installed") or info.get("web") or {}
    print()
    print("=" * 60)
    print("✅ ГОТОВО. Скопируй в Railway → Variables:")
    print("=" * 60)
    print(f"GOOGLE_OAUTH_CLIENT_ID={client_info.get('client_id', '')}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client_info.get('client_secret', '')}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 60)
    print()
    print("Теперь Drive будет работать под твоим Gmail (15 ГБ).")


if __name__ == "__main__":
    main()
