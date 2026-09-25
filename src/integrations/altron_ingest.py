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

# BUG FIX: старый регекс матчил через несколько постов из-за .*? между
# data-post и <div class="tgme_widget_message_text">. Пост без text-div
# сожрал текст следующего поста. Теперь: сначала выделяем границу
# каждого <div class="tgme_widget_message ..."> block, потом внутри
# ищем text и time.
_POST_BOUNDARY_RE = re.compile(
    r'<div\s+class="tgme_widget_message[^"]*"[^>]*data-post="[^/]+/(\d+)"[^>]*>',
    re.DOTALL,
)
_TEXT_IN_POST_RE = re.compile(
    r'<div\s+class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_TIME_IN_POST_RE = re.compile(r'<time\s+datetime="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_posts(html: str) -> list[dict]:
    """Из HTML превью канала достать список постов. Возвращает:
    [{message_id: int, text: str, ts: datetime}, ...]

    Идёт по постам последовательно: находит начало каждого блока, вырезает
    ровно ЕГО фрагмент (до начала следующего), внутри ищет text+time.
    Так пост без текста не заглатывает контент соседей.
    """
    posts: list[dict] = []
    boundaries = list(_POST_BOUNDARY_RE.finditer(html))
    for i, m in enumerate(boundaries):
        try:
            mid = int(m.group(1))
        except Exception:
            continue
        # Фрагмент этого поста: от конца заголовка до начала следующего
        chunk_start = m.end()
        chunk_end = boundaries[i + 1].start() if i + 1 < len(boundaries) else len(html)
        chunk = html[chunk_start:chunk_end]
        # Текст
        tm = _TEXT_IN_POST_RE.search(chunk)
        text_raw = tm.group(1) if tm else ""
        text = text_raw.replace("<br/>", "\n").replace("<br>", "\n")
        text = _TAG_RE.sub("", text)
        text = unescape(text).strip()
        if not text:
            continue
        # Время
        tim = _TIME_IN_POST_RE.search(chunk)
        try:
            ts = datetime.fromisoformat(tim.group(1).replace("Z", "+00:00")) if tim else datetime.now(timezone.utc)
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

    POLL_SEC = 10   # 30 → 10: тревога должна лететь мгновенно
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
        important). Без БД — пустой список.

        BUG FIX: раньше использовали conn.execute() и обращались как к
        ORM-объекту (r.username), но Core Row не имеет атрибутов ORM.
        Переключаем на .scalars() — получаем настоящие ORM объекты.
        """
        try:
            from sqlalchemy import select
            from src.db.models import NewsChannel
            async with self._memory._engine.connect() as conn:
                result = await conn.execute(
                    select(NewsChannel).where(NewsChannel.active == 1)
                )
                rows = result.scalars().all()
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
                    # BUG FIX: раньше self._seen[u] обновлялся сразу при
                    # обнаружении поста. Если далее коллбэк упадёт — пост
                    # уже «помечен виденным» и на ретрае будет пропущен.
                    # Теперь копим pending_seen и применяем ТОЛЬКО после
                    # успешной обработки батча.
                    pending_seen: dict[str, int] = {}
                    for u, posts in zip(channels, results):
                        if isinstance(posts, Exception) or not posts:
                            continue
                        last = self._seen.get(u, 0)
                        for p in sorted(posts, key=lambda x: x["message_id"]):
                            if p["message_id"] <= last:
                                continue
                            pending_seen[u] = max(pending_seen.get(u, 0), p["message_id"])
                            if first_pass:
                                # На первом проходе только запоминаем ID
                                continue
                            text = p["text"]
                            # Только сообщения про юг/Одессу или без явной привязки
                            # (общие всеукраинские) считаем «нашими».
                            # Тревога: SOUTH_RE — жёсткое условие про юг. Ослабляем:
                            # 1) если явно наш регион → alert.
                            # 2) если общая тревога (без региона) + канал не указывает
                            #    другой регион → тоже alert (better safe than sorry).
                            has_start = bool(ALERT_START_RE.search(text))
                            has_clear = bool(ALERT_CLEAR_RE.search(text))
                            is_south = bool(SOUTH_RE.search(text))
                            # Не наш регион явно упомянут (Харьков/Днепр/Сумы etc)
                            other_region = any(
                                r in text.lower() for r in (
                                    "харків", "харков", "дніпр", "днепр",
                                    "сум", "полтав", "зап", "донец", "луган",
                                    "київ", "киев", "черн", "хмельн", "тернопіль",
                                    "івано", "ужгород", "львів", "львов",
                                )
                            )
                            if has_start and (is_south or not other_region):
                                fresh_posts_alerting.append((u, p))
                            elif has_clear and (is_south or not other_region):
                                fresh_posts_clearing.append((u, p))
                            else:
                                fresh_posts_general.append((u, p))

                    if first_pass:
                        # Прайминг — сохраняем все id как виденные, но не
                        # шлём коллбэки.
                        for u, mid in pending_seen.items():
                            self._seen[u] = max(self._seen.get(u, 0), mid)
                        first_pass = False
                        log.info("altron_ingest_primed", channels=len(channels), seen=sum(1 for _ in self._seen))
                    else:
                        try:
                            await self._process_batch(
                                fresh_posts_alerting,
                                fresh_posts_clearing,
                                fresh_posts_general,
                            )
                        except Exception:
                            # Не коммитим pending_seen — на следующем поллинге
                            # эти посты будут повторно обработаны.
                            log.exception("altron_ingest_process_batch_err")
                            raise
                        # Коммитим только после успешной обработки.
                        for u, mid in pending_seen.items():
                            self._seen[u] = max(self._seen.get(u, 0), mid)
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
        # Стартовый пост (если открываем тревогу) — исключим из update-пачки
        starter_id: int | None = None

        # 1. Явное начало тревоги, активной нет — стартуем
        if alerting and self._active is None:
            username, post = alerting[0]
            starter_id = post.get("message_id")
            self._active = {
                "started_at": post["ts"].astimezone().isoformat(),
                "posts": [post],
                "sources": {username},
            }
            try:
                await self._on_start(self.OUR_REGION, post, [username])
            except Exception:
                log.exception("altron_ingest_on_start_cb_err")

        # 2. Явный отбой при активной — закрываем
        if clearing and self._active is not None:
            sources = sorted(self._active["sources"])
            self._active = None
            try:
                await self._on_clear(self.OUR_REGION, sources)
            except Exception:
                log.exception("altron_ingest_on_clear_cb_err")
            return

        # 3. Свежие посты во время активной тревоги — накопить и обновить.
        # BUG FIX: не отправляем стартовый пост как update — он уже ушёл
        # через on_start и вызвал бы дублирование первой карточки.
        if self._active is not None:
            new_posts: list[dict] = []
            for u, p in general + alerting:
                if not u:
                    continue
                if starter_id is not None and p.get("message_id") == starter_id:
                    continue
                self._active["sources"].add(u)
                self._active["posts"].append(p)
                new_posts.append(p)
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
