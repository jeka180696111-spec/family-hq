"""News ingestion: save channel posts to DB, classify alerts via keywords."""
from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import insert, select

from src.db.memory import SharedMemory
from src.db.models import NewsChannel, NewsPost
from src.utils.time import iso_now

log = structlog.get_logger()

_ALERT_PATTERNS = re.compile(
    r"\b("
    r"повітр[яr]на\s+тривога|"
    r"повітр[яr]на\s+загроза|"
    r"тривога|"
    r"відб[іi]й\s+тривоги|"
    r"air\s+raid|air\s+alert|"
    r"шахед|шахеди|"
    r"крилат[аи]\s+ракет[аи]|"
    r"балістичн[аи]\s+ракет[аи]|"
    r"балістика|"
    r"загроза\s+удару|"
    r"запуск\s+ракет"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

_REGION_KEYWORDS = {
    "Одесса": ["одес", "odesa", "odessa"],
    "Киев": ["київ", "киев", "kyiv", "kiev"],
    "Харьков": ["харків", "харьков", "kharkiv"],
    "Львов": ["львів", "львов", "lviv"],
    "Днепр": ["дніпр", "днепр", "dnipro"],
    "Запорожье": ["запоріж", "запорож", "zaporiz"],
    "Николаев": ["микола", "никола", "mykolaiv"],
    "Херсон": ["херсон", "kherson"],
    "Одесская область": ["одеськ", "одесск"],
    "Украина": ["вся україна", "вся украина", "all-ukraine", "all ukraine"],
}


def _detect_alert(text: str) -> tuple[bool, str | None]:
    """Returns (is_alert, region)."""
    if not text:
        return False, None
    if not _ALERT_PATTERNS.search(text):
        return False, None
    lower = text.lower()
    for region, kws in _REGION_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            return True, region
    return True, None


class NewsIngestor:
    """Saves messages from tracked channels to news_posts, flags alerts."""

    def __init__(self, memory: SharedMemory) -> None:
        self._memory = memory
        self._channel_ids: set[int] = set()

    async def load_tracked_channels(self) -> None:
        """Refresh the in-memory set of tracked channel IDs from DB."""
        async with self._memory._engine.connect() as conn:
            rows = await conn.execute(select(NewsChannel.channel_id))
            self._channel_ids = {r[0] for r in rows if r[0]}
        log.info("news_channels_loaded", count=len(self._channel_ids))

    async def handle(self, message: Any) -> None:
        """Called by user-bot for every non-HQ message. Saves if from tracked channel."""
        chat_id = getattr(message, "chat_id", None) or getattr(message, "peer_id", None)
        if chat_id is None:
            return
        # Telethon channel IDs can be negative or positive depending on peer type
        normalized = abs(int(chat_id))
        if normalized not in self._channel_ids and chat_id not in self._channel_ids:
            return

        text = getattr(message, "text", "") or getattr(message, "message", "") or ""
        if not text.strip():
            return

        is_alert, region = _detect_alert(text)

        try:
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    insert(NewsPost).prefix_with("OR IGNORE").values(
                        channel_id=normalized,
                        tg_message_id=int(getattr(message, "id", 0) or 0),
                        text=text[:4000],
                        date=iso_now(),
                        is_alert=1 if is_alert else 0,
                        alert_region=region,
                    )
                )
            log.info(
                "news_post_saved",
                channel_id=normalized,
                is_alert=is_alert,
                region=region,
                preview=text[:80],
            )
        except Exception:
            log.exception("news_post_save_failed", channel_id=normalized)
