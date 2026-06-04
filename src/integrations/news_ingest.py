"""News ingestion: alert state machine, LLM comprehension, address filtering."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, insert, select, update

from src.db.memory import SharedMemory
from src.db.models import ActiveAlert, NewsChannel, NewsPost
from src.utils.family import LOCATION
from src.utils.time import iso_now, now_kyiv

log = structlog.get_logger()


# ─── Patterns ─────────────────────────────────────────────────────────

_ALERT_START_PATTERNS = re.compile(
    r"("
    r"\bповітр[яr]на\s+тривога\b|\bповітр[яr]на\s+загроза\b|"
    r"\bтривога\b|\bтревога\b|"
    r"\bair\s+raid\b|\bair\s+alert\b|"
    r"оголошен[аоу]\s+тривог|объявлена\s+тревог"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_ALERT_CLEAR_PATTERNS = re.compile(
    r"("
    r"\bвідб[іi]й\b|\bотбой\b|"
    r"тривога\s+скасован|тревога\s+отменен|"
    r"alert\s+(over|cleared|cancelled)|"
    r"✅.*тривог|✅.*тревог"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_THREAT_PATTERNS = re.compile(
    r"("
    r"\bшахед\w*|шахіб\w*|"
    r"\bкалібр\w*|калибр\w*|"
    r"\bкрилат[аи]?\s+ракет\w*|балістичн[аи]?\s+ракет\w*|балістика\b|"
    r"\bзапуск\s+ракет\w*|загроза\s+удару|"
    r"\bвибух\w*|взрыв\w*|"
    r"\bобстріл\w*|обстрел\w*|"
    r"\bбпла\b|\bдрон\w*|\bмиг\b|\bтуp\w*|"
    r"\bпуск\w*|"
    r"\bкаб\w*\s*ракет\w*"
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
    "Украина": ["вся україна", "вся украина", "all-ukraine"],
}

_NON_ALERT_TOPICS = re.compile(
    r"\b("
    r"ціни|цены|вартість|стоимость|подорожч|подорожанн|"
    r"бензин|пальн[еі]|АЗС|тариф|"
    r"курс\s+(долар|евро|гривн|долл)|"
    r"футбол|матч|чемпіонат|чемпионат|збірн[аоі]|"
    r"вибор[иыа]|политик|політик|депутат|"
    r"економік|экономик|бюджет|кредит|"
    r"гороскоп|зірк|звезд|погод[аи]|прогноз\s+погод"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_PROMO_PATTERNS = re.compile(
    r"(прислати?ь?\s+новост|плат(им|ять)\s+за\s+контент|"
    r"реклам[аи]?|sponsorship|наш(а|и)\s+ресурс|"
    r"подп[иі]ши(сь|тесь)|будь?те\s+в\s+курсе|"
    r"оперативные?\s+новости|ссылка\s+на\s+канал|"
    r"в\s+режиме\s+онлайн|24/?7)",
    re.IGNORECASE | re.UNICODE,
)


def _strip_promo(text: str) -> str:
    lines = text.splitlines()
    clean: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _PROMO_PATTERNS.search(stripped):
            break
        if stripped.startswith("https://t.me/") or stripped.startswith("t.me/"):
            continue
        if stripped in ("—", "---", "===", "~~~", "***"):
            continue
        clean.append(line)
    while clean and not clean[-1].strip():
        clean.pop()
    return "\n".join(clean).strip() or text.strip()


def _classify(text: str) -> tuple[str, str | None]:
    """Returns (status, region). status ∈ {alert_start, alert_update, alert_clear, none}."""
    if not text:
        return "none", None
    if _NON_ALERT_TOPICS.search(text):
        # Hard veto: looks like economy/sport/politics, not an alert
        return "none", None

    region = _detect_region(text)

    if _ALERT_CLEAR_PATTERNS.search(text):
        return "alert_clear", region

    if _ALERT_START_PATTERNS.search(text):
        return "alert_start", region

    if _THREAT_PATTERNS.search(text):
        # шахед/пуск/обстріл — content update during alert (no тревога/відбій keywords)
        return "alert_update", region

    return "none", region


def _detect_region(text: str) -> str | None:
    lower = text.lower()
    for region, kws in _REGION_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            return region
    return None


# ─── Home address detection (for utility channels) ───────────────────

_HOME_ADDRESS_KEYWORDS = [
    "армейская 12", "армейская 12/2", "армейская, 12",
    "армійська 12", "армійська 12/2",
    "независимости 12", "независимости 12/2", "независимости, 12",
    "незалежності 12", "незалежності 12/2",
    f"{LOCATION['district'].lower()}",  # «приморский район»
    "приморский район", "приморський район",
]


def _mentions_home(text: str) -> bool:
    lower = text.lower()
    return any(addr in lower for addr in _HOME_ADDRESS_KEYWORDS)


# ─── Ingestor ────────────────────────────────────────────────────────

class NewsIngestor:
    """
    Alert pipeline with state machine:
      alert_start → push «🚨 ТРЕВОГА — region», create ActiveAlert
      alert_update (while ActiveAlert exists) → push «🔄 ОБНОВЛЕНИЕ: <что/куда>»
      alert_clear → push «✅ ОТБОЙ — region, длилось Xмин», delete ActiveAlert
      auto-close ActiveAlert after 60 min of silence
    Utility channels: only push if message mentions home address.
    """

    def __init__(
        self,
        memory: SharedMemory,
        bot_manager: Any = None,
        chat_id: int | None = None,
        claude_client: Any = None,
        model_cheap: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._memory = memory
        self._channel_ids: set[int] = set()
        self._channel_meta: dict[int, dict] = {}
        self._bots = bot_manager
        self._chat_id = chat_id
        self._claude = claude_client
        self._model = model_cheap

    async def load_tracked_channels(self) -> None:
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
        meta = self._channel_meta.get(normalized, {})

        text = getattr(message, "text", "") or getattr(message, "message", "") or ""
        has_media = bool(getattr(message, "media", None) or getattr(message, "photo", None))

        # Media-only
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

        status, region = _classify(text)
        if status != "none" and not region:
            region = meta.get("region")

        # Save post first
        try:
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    insert(NewsPost).prefix_with("OR IGNORE").values(
                        channel_id=normalized,
                        tg_message_id=int(getattr(message, "id", 0) or 0),
                        text=text[:4000],
                        date=iso_now(),
                        is_alert=1 if status in ("alert_start", "alert_update") else 0,
                        alert_region=region,
                    )
                )
        except Exception:
            log.exception("news_post_save_failed", channel_id=normalized)

        log.info("news_post_classified", channel_id=normalized, status=status, region=region, preview=text[:80])

        # Routing per category
        if not (self._bots and self._chat_id):
            return

        category = meta.get("category", "")

        # Utility channels: address-filtered push
        if category == "utility":
            if _mentions_home(text):
                await self._push_utility(text, meta)
            return

        # Critical channels: state-machine alerts
        if category == "critical" and region:
            await self._handle_alert_event(status, region, text, meta)

    async def _handle_alert_event(self, status: str, region: str, text: str, meta: dict) -> None:
        active = await self._get_active(region)

        if status == "alert_start":
            if active:
                # Already active — treat as update if there's threat detail
                if _THREAT_PATTERNS.search(text):
                    await self._push_update(region, text, meta)
                else:
                    log.info("alert_start_repeat_ignored", region=region)
                return
            await self._open_alert(region, meta.get("username") or "")
            await self._push_start(region, text, meta)
            return

        if status == "alert_update":
            if active:
                await self._push_update(region, text, meta)
            # If no active alert, ignore — random шахед mention without тревога
            return

        if status == "alert_clear":
            if active:
                await self._close_alert(region, text, active)
            return

    # ─── Active-alert DB ─────────────────────────────────────────────

    async def _get_active(self, region: str) -> dict | None:
        async with self._memory._engine.connect() as conn:
            row = (await conn.execute(
                select(ActiveAlert).where(ActiveAlert.region == region)
            )).first()
        if not row:
            return None
        return {
            "region": row.region,
            "started_at": row.started_at,
            "sources": row.sources,
            "announced_at": row.announced_at,
            "last_update_at": row.last_update_at,
        }

    async def _open_alert(self, region: str, source: str) -> None:
        now = iso_now()
        async with self._memory._engine.begin() as conn:
            await conn.execute(
                insert(ActiveAlert).prefix_with("OR REPLACE").values(
                    region=region,
                    started_at=now,
                    sources=json.dumps([source] if source else []),
                    announced_at=now,
                    last_update_at=now,
                )
            )
        log.info("alert_opened", region=region, source=source)

    async def _close_alert(self, region: str, text: str, active: dict) -> None:
        try:
            started = datetime.fromisoformat(active["started_at"])
            duration_min = int((now_kyiv() - started).total_seconds() / 60)
        except Exception:
            duration_min = 0

        async with self._memory._engine.begin() as conn:
            await conn.execute(delete(ActiveAlert).where(ActiveAlert.region == region))

        msg = (
            f"✅ <b>ОТБОЙ — {region}</b>\n"
            f"Длилась: {duration_min} мин"
        )
        try:
            await self._bots.send_message(agent_id="news", chat_id=self._chat_id, text=msg)
            log.info("alert_closed", region=region, duration_min=duration_min)
        except Exception:
            log.exception("alert_close_push_failed")

    async def _touch_alert(self, region: str) -> None:
        async with self._memory._engine.begin() as conn:
            await conn.execute(
                update(ActiveAlert).where(ActiveAlert.region == region).values(last_update_at=iso_now())
            )

    # ─── Pushes ──────────────────────────────────────────────────────

    async def _push_start(self, region: str, text: str, meta: dict) -> None:
        snippet = await self._summarize(text, mode="start")
        src = meta.get("username") or "канал"
        msg = (
            f"🚨🚨🚨 <b>ТРЕВОГА — {region}</b>\n\n"
            f"{snippet}\n\n"
            f"<i>Источник: @{src}</i>"
        )
        try:
            await self._bots.send_message(agent_id="news", chat_id=self._chat_id, text=msg)
            log.info("alert_start_pushed", region=region)
        except Exception:
            log.exception("alert_start_push_failed")

    async def _push_update(self, region: str, text: str, meta: dict) -> None:
        await self._touch_alert(region)
        snippet = await self._summarize(text, mode="update")
        if not snippet:
            log.info("alert_update_skipped_empty", region=region)
            return
        src = meta.get("username") or "канал"
        msg = (
            f"🔄 <b>{region} — обновление</b>\n\n"
            f"{snippet}\n\n"
            f"<i>@{src}</i>"
        )
        try:
            await self._bots.send_message(agent_id="news", chat_id=self._chat_id, text=msg)
            log.info("alert_update_pushed", region=region)
        except Exception:
            log.exception("alert_update_push_failed")

    async def _push_utility(self, text: str, meta: dict) -> None:
        snippet = _strip_promo(text)
        if len(snippet) > 600:
            snippet = snippet[:600] + "…"
        src = meta.get("username") or "канал"
        msg = (
            f"🏠 <b>По вашему адресу</b>\n\n"
            f"{snippet}\n\n"
            f"<i>@{src}</i>"
        )
        try:
            await self._bots.send_message(agent_id="news", chat_id=self._chat_id, text=msg)
            log.info("utility_pushed", source=src)
        except Exception:
            log.exception("utility_push_failed")

    # ─── LLM summarization ───────────────────────────────────────────

    async def _summarize(self, text: str, mode: str) -> str:
        """Use Claude Haiku to extract structured alert info. Falls back to stripped text."""
        cleaned = _strip_promo(text)
        if not self._claude:
            if len(cleaned) > 400:
                return cleaned[:400] + "…"
            return cleaned

        try:
            if mode == "start":
                prompt = (
                    "Сообщение из военно-новостного канала. Извлеки СУТЬ тревоги в 1-2 коротких строки: "
                    "что объявлено (тревога/удар), угроза (шахед/ракета/КАБ если упомянуто), "
                    "регион/город. Без воды, без эмодзи в начале. Если в тексте нет содержательной "
                    "информации (просто слово 'тревога' и регион) — верни ровно 'NEW_ALERT'.\n\n"
                    f"Текст:\n{cleaned}\n\nКраткий ответ:"
                )
            else:
                prompt = (
                    "Сообщение из военно-новостного канала ВО ВРЕМЯ активной тревоги. "
                    "Извлеки ТОЛЬКО новую конкретную информацию: что замечено (шахед/ракета/КАБ), "
                    "куда летит/где находится (район/направление), время если указано, последствия "
                    "(взрыв/работа ПВО/удар). Без общих фраз. 1-3 коротких строки. "
                    "Если новой инфы нет (просто повтор 'тревога' или 'ожидаем отбой') — "
                    "верни ровно 'NO_NEW_INFO'.\n\n"
                    f"Текст:\n{cleaned}\n\nКраткий ответ:"
                )

            response = await self._claude.complete(
                model=self._model,
                system="Ты — военно-новостной аналитик. Отвечай максимально кратко, по фактам.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            result = (response or "").strip()
            if result in ("NO_NEW_INFO", "NEW_ALERT", ""):
                if result == "NO_NEW_INFO":
                    return ""
                # NEW_ALERT or empty: fallback to cleaned snippet
                if len(cleaned) > 400:
                    return cleaned[:400] + "…"
                return cleaned
            return result
        except Exception:
            log.exception("summarize_failed")
            if len(cleaned) > 400:
                return cleaned[:400] + "…"
            return cleaned

    # ─── Auto-close watchdog ─────────────────────────────────────────

    async def auto_close_stale(self) -> int:
        """Close active alerts with no updates for 60 min. Called by scheduler every 5 min."""
        cutoff = (now_kyiv() - timedelta(minutes=60)).isoformat()
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(ActiveAlert).where(ActiveAlert.last_update_at < cutoff)
            ))

        closed = 0
        for r in rows:
            try:
                started = datetime.fromisoformat(r.started_at)
                duration_min = int((now_kyiv() - started).total_seconds() / 60)
            except Exception:
                duration_min = 0
            async with self._memory._engine.begin() as conn:
                await conn.execute(delete(ActiveAlert).where(ActiveAlert.region == r.region))
            if self._bots and self._chat_id:
                msg = (
                    f"✅ <b>ОТБОЙ — {r.region}</b>\n"
                    f"Длилась: {duration_min} мин (авто-закрытие по тайм-ауту)"
                )
                try:
                    await self._bots.send_message(agent_id="news", chat_id=self._chat_id, text=msg)
                except Exception:
                    log.exception("auto_close_push_failed", region=r.region)
            closed += 1
            log.info("alert_auto_closed", region=r.region, duration_min=duration_min)
        return closed
