"""Собственный сборщик постов из Telegram-каналов для Альтрона.

Не зависит от штабного news_ingest (который через MTProto userbot).
Читает публичные превью каналов через веб — https://t.me/s/<username> —
парсит последние посты, детектит тревоги и передаёт коллбэком в бота.

Ограничения (осознанные):
- Только публичные каналы (у которых есть username и открытые сообщения).
- Задержка ~10-30 сек (пока Telegram обновит превью на CDN).
- Медиа игнорируем, берём только текст.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()


# ─── Alert-обнаружение (свой набор, независимо от news_ingest) ────────

ALERT_START_RE = re.compile(
    r"("
    r"\bповітр[яr]на\s+тривог|повітряна\s+загроз|"
    r"\bтривог[аи]?\b|\bтревог[аи]?\b|"
    r"\bair\s+raid\b|"
    r"оголошен[аоу]\s+тривог|объявлена\s+тревог"
    r")",
    re.IGNORECASE,
)

ALERT_CLEAR_RE = re.compile(
    r"("
    r"\bвідб[іi]й\b|\bотбой\b|"
    r"тривога\s+скасован|тревога\s+отменен|"
    r"тривог[аи]?\s+знят|тревог[аи]?\s+снят|"
    r"минула\s+загроз|небо\s+чист|"
    r"✅.*тривог|✅.*тревог|✅.*відб|✅.*отбой"
    r")",
    re.IGNORECASE,
)

# Признак что тревога/угроза касается ЮГА (Одесса).
SOUTH_RE = re.compile(
    r"(одес|южн|затока|каролин|черноморск|іллічівськ|чорноморськ|"
    r"овідіополь|овидиополь|миколаїв|николаев|аркад[иі][яi])",
    re.IGNORECASE,
)


# ─── Парсинг t.me/s/<username> ────────────────────────────────────────

_POST_RE = re.compile(
    r'<div\s+class="tgme_widget_message[^"]*"[^>]*data-post="[^/]+/(\d+)"[^>]*>.*?'
    r'(?:<div\s+class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>)?'
    r'.*?<time\s+datetime="([^"]+)"',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_posts(html: str) -> list[dict]:
    """Из HTML превью канала достать список постов новее сверху.

    Возвращает: [{message_id: int, text: str, ts: datetime}, ...]
    """
    posts: list[dict] = []
    for m in _POST_RE.finditer(html):
        try:
            mid = int(m.group(1))
        except Exception:
            continue
        text_raw = m.group(2) or ""
        # <br> → \n, срезаем остальные теги, распаковываем entities
        text = text_raw.replace("<br/>", "\n").replace("<br>", "\n")
        text = _TAG_RE.sub("", text)
        text = unescape(text).strip()
        if not text:
            continue
        try:
            ts = datetime.fromisoformat(m.group(3).replace("Z", "+00:00"))
        except Exception:
            ts = datetime.now(timezone.utc)
        posts.append({"message_id": mid, "text": text, "ts": ts})
    return posts


async def fetch_channel(session: aiohttp.ClientSession, username: str) -> list[dict]:
    """Забрать последние посты канала через публичное превью."""
    u = username.lstrip("@")
    url = f"https://t.me/s/{u}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
    except Exception:
        return []
    return _extract_posts(html)


# ─── Публичное API — используется из AltronBot ────────────────────────

class AltronDirectIngestor:
    """Опрашивает список каналов, накапливает свежие посты, детектит
    начало/конец воздушной тревоги. Никакого штабного дозорного.

    Bot передаёт колбэки:
      - on_alert_start(region: str, first_post: dict, sources: list[str])
      - on_alert_update(region: str, new_posts: list[dict], sources: list[str])
      - on_alert_clear(region: str, sources: list[str])
    """

    POLL_SEC = 30
    OUR_REGION = "Одеська область"

    def __init__(
        self,
        memory: Any,
        on_alert_start,
        on_alert_update,
        on_alert_clear,
    ) -> None:
        self._memory = memory
        self._on_start = on_alert_start
        self._on_update = on_alert_update
        self._on_clear = on_alert_clear
        # {channel_username: last_seen_msg_id}
        self._seen: dict[str, int] = {}
        # Активная тревога (только одну ведём — «наш» регион).
        # {"started_at": iso, "posts": [...], "sources": {username}}
        self._active: dict | None = None

    async def _load_channels(self) -> list[str]:
        """Список username-ов каналов из NewsChannel (только critical +
        important). Без БД — пустой список."""
        try:
            from sqlalchemy import select
            from src.db.models import NewsChannel
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(NewsChannel).where(NewsChannel.active == 1)
                ))
        except Exception:
            log.exception("altron_ingest_load_channels_failed")
            return []
        out: list[str] = []
        for r in rows:
            u = (r.username or "").lstrip("@")
            cat = (r.category or "").lower()
            if u and cat in ("critical", "important"):
                out.append(u)
        return out

    async def run(self) -> None:
        """Основной цикл. Останавливается CancelledError."""
        # Разогрев на первом проходе — только зафиксировать состояние,
        # без коллбэков (иначе спам «тревога» на старте).
        first_pass = True
        async with aiohttp.ClientSession(
            headers={"User-Agent": "AltronDirectIngestor/1.0"}
        ) as session:
            while True:
                try:
                    channels = await self._load_channels()
                    if not channels:
                        await asyncio.sleep(self.POLL_SEC * 2)
                        continue

                    fresh_posts_alerting: list[tuple[str, dict]] = []
                    fresh_posts_clearing: list[tuple[str, dict]] = []
                    fresh_posts_general: list[tuple[str, dict]] = []

                    # Параллельно грузим все каналы
                    results = await asyncio.gather(
                        *[fetch_channel(session, u) for u in channels],
                        return_exceptions=True,
                    )
                    for u, posts in zip(channels, results):
                        if isinstance(posts, Exception) or not posts:
                            continue
                        last = self._seen.get(u, 0)
                        for p in sorted(posts, key=lambda x: x["message_id"]):
                            if p["message_id"] <= last:
                                continue
                            self._seen[u] = p["message_id"]
                            if first_pass:
                                # На первом проходе только запоминаем ID
                                continue
                            text = p["text"]
                            # Только сообщения про юг/Одессу или без явной привязки
                            # (общие всеукраинские) считаем «нашими».
                            if ALERT_START_RE.search(text) and SOUTH_RE.search(text):
                                fresh_posts_alerting.append((u, p))
                            elif ALERT_CLEAR_RE.search(text) and SOUTH_RE.search(text):
                                fresh_posts_clearing.append((u, p))
                            else:
                                fresh_posts_general.append((u, p))

                    if first_pass:
                        first_pass = False
                        log.info("altron_ingest_primed", channels=len(channels), seen=sum(1 for _ in self._seen))
                    else:
                        await self._process_batch(
                            fresh_posts_alerting,
                            fresh_posts_clearing,
                            fresh_posts_general,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("altron_ingest_loop_err")
                try:
                    await asyncio.sleep(self.POLL_SEC)
                except asyncio.CancelledError:
                    raise

    async def _process_batch(
        self,
        alerting: list[tuple[str, dict]],
        clearing: list[tuple[str, dict]],
        general: list[tuple[str, dict]],
    ) -> None:
        # 1. Если пришло явное начало тревоги, а активной нет — стартуем
        if alerting and self._active is None:
            username, post = alerting[0]
            self._active = {
                "started_at": post["ts"].astimezone().isoformat(),
                "posts": [post],
                "sources": {username},
            }
            try:
                await self._on_start(self.OUR_REGION, post, [username])
            except Exception:
                log.exception("altron_ingest_on_start_cb_err")

        # 2. Если явный отбой пришёл при активной — закрываем
        if clearing and self._active is not None:
            sources = sorted(self._active["sources"])
            self._active = None
            try:
                await self._on_clear(self.OUR_REGION, sources)
            except Exception:
                log.exception("altron_ingest_on_clear_cb_err")
            return

        # 3. Свежие посты во время активной тревоги — добавляем и апдейтим
        if self._active is not None:
            new_posts: list[dict] = []
            for u, p in general + alerting:
                if u == "":
                    continue
                # Только если пост актуален (после старта тревоги)
                self._active["sources"].add(u)
                self._active["posts"].append(p)
                new_posts.append(p)
            # Ограничиваем буфер — не даём разрастаться
            self._active["posts"] = self._active["posts"][-40:]
            if new_posts:
                try:
                    await self._on_update(
                        self.OUR_REGION,
                        new_posts,
                        sorted(self._active["sources"]),
                    )
                except Exception:
                    log.exception("altron_ingest_on_update_cb_err")
