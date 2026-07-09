"""Shopper — поиск товаров в украинских магазинах.

Первая версия: только Rozetka (публичный поиск, HTML-парсинг). Позже
можно добавить OLX / Prom / Amazon.

Работает без API-ключей. Не выдумывает — если поиск пуст, возвращает
пустой список и Дворецкий скажет «ничего не нашлось».
"""
from __future__ import annotations
import re
import asyncio
from html import unescape
from urllib.parse import quote_plus

import httpx
import structlog

log = structlog.get_logger()

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept-Language": "uk,ru;q=0.9,en;q=0.7"}


class ShopperClient:
    """Поиск товаров. Каждый метод не бросает — при ошибке пустой список."""

    async def search(
        self,
        query: str,
        max_price: int | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        results = await self._search_rozetka(query, max_price, limit)
        # Урезаем до limit — на случай если несколько источников
        return results[:limit]

    async def _search_rozetka(
        self, query: str, max_price: int | None, limit: int
    ) -> list[dict]:
        """Rozetka: используем публичный поиск по HTML."""
        url = f"https://rozetka.com.ua/ua/search/?text={quote_plus(query)}"
        if max_price:
            url += f"&price=0;{max_price}"
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, timeout=15.0, follow_redirects=True
            ) as client:
                r = await client.get(url)
                r.raise_for_status()
                html = r.text
        except Exception as e:
            log.warning("rozetka_search_failed", error=str(e)[:120])
            return []

        # Rozetka карточки: ищем блоки с классом goods-tile
        # Название в <span class="goods-tile__title">…</span>,
        # цена в <p class="goods-tile__price-value">…</p>,
        # ссылка в <a class="goods-tile__heading" href="...">.
        results: list[dict] = []
        # Простая эвристика — регулярки, чтобы не тащить BeautifulSoup
        card_re = re.compile(
            r'<a[^>]+class="[^"]*goods-tile__heading[^"]*"[^>]+href="(?P<url>[^"]+)"[^>]*>.*?'
            r'<span[^>]+class="[^"]*goods-tile__title[^"]*"[^>]*>(?P<title>.*?)</span>.*?'
            r'(?:goods-tile__price-value[^>]*>(?P<price>[^<]*)</)',
            re.DOTALL,
        )
        for m in card_re.finditer(html):
            title = unescape(re.sub(r"<[^>]+>", "", m.group("title"))).strip()
            price_raw = unescape(re.sub(r"<[^>]+>", "", m.group("price") or "")).strip()
            price_num = int(re.sub(r"\D", "", price_raw) or 0) or None
            link = m.group("url")
            if not title or not link:
                continue
            if max_price and price_num and price_num > max_price:
                continue
            results.append({
                "title": title[:120],
                "price_uah": price_num,
                "price_raw": price_raw,
                "url": link,
                "store": "Rozetka",
            })
            if len(results) >= limit:
                break
        log.info("rozetka_search", query=query[:60], found=len(results))
        return results
