from __future__ import annotations
from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
import base64
import json


class Settings(BaseSettings):
    # Telegram bots (6 internal agents; Фінн is external)
    nanny_bot_token: str = Field(default="")
    news_bot_token: str = Field(default="")
    calendar_bot_token: str = Field(default="")
    cook_bot_token: str = Field(default="")
    health_bot_token: str = Field(default="")
    devops_bot_token: str = Field(default="")

    # Telethon — accepts TELEGRAM_API_ID or TG_API_ID
    tg_api_id: int = Field(
        default=0,
        validation_alias=AliasChoices("tg_api_id", "telegram_api_id"),
    )
    tg_api_hash: str = Field(
        default="",
        validation_alias=AliasChoices("tg_api_hash", "telegram_api_hash"),
    )
    tg_session_name: str = Field(default="family_hq_user")
    tg_session_string: str = Field(default="")
    tg_phone: str = Field(default="")

    # Group — accepts HQ_CHAT_ID or TELEGRAM_GROUP_ID
    hq_chat_id: int = Field(
        default=0,
        validation_alias=AliasChoices("hq_chat_id", "telegram_group_id"),
    )

    # Owners
    owner_husband_id: int = Field(default=0)
    owner_wife_id: int = Field(default=0)
    owner_husband_name: str = Field(default="Муж")
    owner_wife_name: str = Field(default="Жена")

    # Anthropic — accepts ANTHROPIC_API_KEY_PRIMARY or ANTHROPIC_API_KEY
    anthropic_api_key_primary: str = Field(
        default="",
        validation_alias=AliasChoices("anthropic_api_key_primary", "anthropic_api_key"),
    )
    anthropic_api_key_backup: str = Field(default="")
    model_main: str = Field(default="claude-sonnet-4-5-20250929")
    model_cheap: str = Field(default="claude-haiku-4-5-20251001")

    # Google — accepts both naming styles
    google_service_account_b64: str = Field(default="")
    sheet_baby_id: str = Field(
        default="",
        validation_alias=AliasChoices("sheet_baby_id", "sheets_baby_id"),
    )
    drive_backup_folder_id: str = Field(
        default="",
        validation_alias=AliasChoices("drive_backup_folder_id", "gdrive_backup_folder_id"),
    )
    calendar_id: str = Field(
        default="",
        validation_alias=AliasChoices("calendar_id", "gcalendar_id"),
    )

    # GitHub
    github_token: str = Field(default="")
    github_repo: str = Field(default="owner/family-hq")

    # Railway
    railway_api_token: str = Field(default="")
    railway_project_id: str = Field(default="")
    matveika_service_id: str = Field(default="")

    # Tuya / Smart Life
    tuya_access_id: str = Field(default="")
    tuya_access_secret: str = Field(default="")
    tuya_region: str = Field(default="eu")
    tuya_app_user_uid: str = Field(default="")

    # LuxCloud / LuxPower inverter
    luxcloud_email: str = Field(default="")
    luxcloud_password: str = Field(default="")
    luxcloud_region: str = Field(default="eu")
    lux_inverter_serial: str = Field(default="")
    # Battery capacity in Wh — used to estimate runtime during outages.
    # Default = 108 Ah × 48 V = 5184 Wh (LiFePO4 15S server-rack pack).
    battery_capacity_wh: int = Field(default=5184)
    # Cut-off SOC% — autonomy is computed down to this level, not 0.
    battery_reserve_pct: int = Field(default=20)

    # SmartThings (Samsung POWERbot, other ST-connected devices)
    smartthings_token: str = Field(default="")

    # OpenWeatherMap
    openweather_api_key: str = Field(default="")

    # Google Maps (Directions + Places) — for Штурман
    gmaps_api_key: str = Field(default="")

    # OpenAI — for Whisper voice transcription
    openai_api_key: str = Field(default="")

    # Nova Poshta tracking — single key, user pastes TTNs manually in chat
    nova_poshta_api_key: str = Field(default="")

    # Google Gemini API — text fallback when Anthropic is unavailable
    # (no credits / outage / rate limit). Free tier: 1500 req/day Flash.
    gemini_api_key: str = Field(default="")
    # Comma-separated extra keys to rotate through when the primary one
    # hits 429/quota or a model-access issue. Order matters — earlier wins.
    gemini_api_keys: str = Field(default="")
    gemini_model: str = Field(default="gemini-1.5-flash")

    # Web dashboard auth — random secret a user pastes in URL ?token=
    dashboard_token: str = Field(default="")

    # Google Drive folder for baby photo archive (separate from db backup folder)
    baby_photos_drive_folder_id: str = Field(default="")

    # Master Drive folder — agents auto-create subfolders inside it:
    #   👶 Матвей · Фото / YYYY-MM /
    #   ⛽ Чеки · АЗС / YYYY-MM /
    #   🏥 Здоровье · <member> /
    #   🍳 Рецепты /
    # Falls back to baby_photos_drive_folder_id, then to drive_backup_folder_id.
    drive_root_folder_id: str = Field(default="")

    # Telegram channel ID for media archive (workaround for Drive SA quota issue).
    # Format: -100xxxxxxxxxx
    baby_photo_archive_channel_id: int = Field(default=0)

    # OAuth path for Drive — lets files be uploaded under the OWNER's
    # 15 GB Gmail quota instead of failing on the SA's 0-quota. Set up
    # once via scripts/setup_drive_oauth.py.
    google_oauth_client_id: str = Field(default="")
    google_oauth_client_secret: str = Field(default="")
    google_oauth_refresh_token: str = Field(default="")

    # Optional separate Telegram bot for Штурман; falls back to devops bot if empty
    navigator_bot_token: str = Field(default="")

    # Дворецкий — умный дом (Tuya/сцены/инвертор) + Шопер (поиск товаров).
    # Falls back to devops bot if empty (для миграции).
    butler_bot_token: str = Field(default="")

    # Калибровка датчика температуры/влажности (дешёвые Tuya-датчики
    # завышают/занижают на 1-2°C). Значения ПРИБАВЛЯЮТСЯ к показанию.
    # Пример: если датчик пишет 25°C а реально 23°C → offset=-2.
    sensor_temp_offset: float = Field(default=0.0)
    sensor_humidity_offset: float = Field(default=0.0)

    # Проактивный мониторинг детской: диапазоны нормы (WHO/AAP)
    baby_room_temp_min: float = Field(default=18.0)
    baby_room_temp_max: float = Field(default=24.0)
    baby_room_humidity_min: float = Field(default=40.0)
    baby_room_humidity_max: float = Field(default=60.0)
    baby_room_sensor_name: str = Field(default="детская")  # подстрока в имени датчика

    # UI mode (enhanced = inline keyboards, edit-in-place, charts; classic = rollback)
    ui_mode: str = Field(default="enhanced")

    # Telegram topics (set if group is supergroup with topics enabled)
    topic_baby_id: int = Field(default=0)
    topic_news_id: int = Field(default=0)
    topic_home_id: int = Field(default=0)
    topic_finance_id: int = Field(default=0)
    topic_calendar_id: int = Field(default=0)
    topic_system_id: int = Field(default=0)

    # App settings
    timezone: str = Field(default="Europe/Kyiv")
    digest_time: str = Field(default="08:00")
    night_mode_start: str = Field(default="00:00")
    night_mode_end: str = Field(default="06:00")
    log_level: str = Field(default="INFO")
    db_path: str = Field(default="/data/family_hq.db")
    enable_userbot: bool = Field(default=False)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "populate_by_name": True,
    }

    @property
    def owner_ids(self) -> list[int]:
        return [x for x in [self.owner_husband_id, self.owner_wife_id] if x]

    @property
    def google_service_account_json(self) -> dict:
        if not self.google_service_account_b64:
            return {}
        return json.loads(base64.b64decode(self.google_service_account_b64))

    def get_bot_token(self, agent_id: str) -> str:
        """Get bot token for a given agent_id."""
        mapping: dict[str, str] = {
            "nanny": self.nanny_bot_token,
            "news": self.news_bot_token,
            "calendar": self.calendar_bot_token,
            "cook": self.cook_bot_token,
            "health": self.health_bot_token,
            "devops": self.devops_bot_token,
        }
        return mapping.get(agent_id, "")


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
