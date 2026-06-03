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
    r"("
    r"\bповітр[яr]на\s+тривога\b|"
    r"\bповітр[яr]на\s+загроза\b|"
    r"\bтривога\b|"
    r"\bтревога\b|"
    r"\bвідб[іi]й\b|"
    r"\bотбой\b|"
    r"\bair\s+raid\b|\bair\s+alert\b|"
    r"\bшахед\w*|шахіб\w*|"
    r"\bкалібр\w*|калибр\w*|"
    r"\bкрилат[аи]?\s+ракет\w*|"
    r"\bбалістичн[аи]?\s+ракет\w*|"
    r"\bбалістика\b|"
    r"\bзагроза\s+удару\b|"
    r"\bзапуск\s+ракет\w*|"
    r"\bвибух\w*|взрыв\w*|"
    r"\bобстріл\w*|обстрел\w*|"
    r"\bкаб\w*\s*ракет\w*|"
    r"🚨|⚠️\s*тривога|⚠️\s*тревога"
    r")",
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
    """Saves messages from tracked channels to news_posts, flags alerts, pushes critical alerts."""

    def __init__(self, memory: SharedMemory, bot_manager: Any = None, chat_id: int | None = None) -> None:
        self._memory = memory
        self._channel_ids: set[int] = set()
        self._channel_meta: dict[int, dict] = {}
        self._bots = bot_manager
        self._chat_id = chat_id
        # Dedup window for alerts: don't push more than once per region per 5 minutes
        self._last_alert_push: dict[str, str] = {}

    async def load_tracked_channels(self) -> None:
        """Refresh the in-memory set of tracked channel IDs + metadata from DB."""
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(select(NewsChannel)))
        ids: set[int] = set()
        meta: dict[int, dict] = {}
        for r in rows:
            if r.channel_id:
                ids.add(r.channel_id)
                meta[r.channel_id] = {
                    "username": r.username,
                    "title": r.title,
                    "category": r.category,
                    "region": r.region,
                }
        self._channel_ids = ids
        self._channel_meta = meta
        log.info("news_channels_loaded", count=len(self._channel_ids))

    async def handle(self, message: Any) -> None:
        """Called by user-bot for every non-HQ message. Saves if from tracked channel."""
        chat_id = getattr(message, "chat_id", None) or getattr(message, "peer_id", None)
        if chat_id is None:
            return
        candidates: set[int] = set()
        try:
            raw = int(chat_id)
        except Exception:
            return
        candidates.add(raw)
        absolute = abs(raw)
        candidates.add(absolute)
        if absolute > 1_000_000_000_000:
            candidates.add(absolute - 1_000_000_000_000)

        match_id = next((c for c in candidates if c in self._channel_ids), None)
        if match_id is None:
            return
        normalized = match_id

        text = getattr(message, "text", "") or getattr(message, "message", "") or ""
        has_media = bool(getattr(message, "media", None) or getattr(message, "photo", None))

        # Variant A: track media-only posts as activity markers (no analysis yet)
        if not text.strip():
            if has_media:
                try:
                    async with self._memory._engine.begin() as conn:
                        await conn.execute(
                            insert(NewsPost).prefix_with("OR IGNORE").values(
                                channel_id=normalized,
                                tg_message_id=int(getattr(message, "id", 0) or 0),
                                text="[медиа без подписи]",
                                date=iso_now(),
                                is_alert=0,
                                alert_region=None,
                            )
                        )
                    log.info("news_post_media_only", channel_id=normalized)
                except Exception:
                    log.exception("news_media_save_failed", channel_id=normalized)
            return

        is_alert, region = _detect_alert(text)
        meta = self._channel_meta.get(normalized, {})

        # Heuristic: short urgent-looking posts from CRITICAL channels are alerts even
        # if our regex didn't match (e.g. "🚨🚨🚨 Одеса, ховаємось"). Avoids missing
        # alerts when source posts in shorthand.
        if not is_alert and meta.get("category") == "critical":
            short = len(text) <= 200
            urgent_marker = ("🚨" in text or "❗" in text or "⚠️" in text
                             or text.strip().endswith("!!!"))
            if short and urgent_marker:
                is_alert = True

        # If channel itself is tagged as a region, inherit it
        if is_alert and not region:
            region = meta.get("region")

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

        # Proactive push: alerts from critical-category channels go straight to HQ group
        if is_alert and self._bots and self._chat_id:
            category = meta.get("category", "")
            if category == "critical":
                await self._maybe_push_alert(text, region, meta)

    async def _maybe_push_alert(self, text: str, region: str | None, meta: dict) -> None:
        """Send a Дозорный bot message to HQ for a critical alert, deduped per region."""
        from datetime import datetime, timedelta
        from src.utils.time import now_kyiv
        now = now_kyiv()
        key = region or meta.get("username", "global")
        last_iso = self._last_alert_push.get(key)
        if last_iso:
            try:
                last = datetime.fromisoformat(last_iso)
                if (now - last) < timedelta(minutes=5):
                    log.info("alert_push_skipped_dedup", region=key)
                    return
            except Exception:
                pass
        self._last_alert_push[key] = now.isoformat()

        snippet = text.strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + "…"
        region_label = region or "регион"
        src = meta.get("username") or meta.get("title") or "канал"
        message = (
            f"🚨🚨🚨 <b>ТРЕВОГА — {region_label}</b>\n\n"
            f"{snippet}\n\n"
            f"<i>Источник: @{src}</i>"
        )
        try:
            await self._bots.send_message(
                agent_id="news",
                chat_id=self._chat_id,
                text=message,
            )
            log.info("alert_pushed", region=region_label, source=src)
        except Exception:
            log.exception("alert_push_failed")
