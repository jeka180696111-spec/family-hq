"""Shopper — поиск товаров в украинских магазинах.

Магазины: Rozetka, Comfy, Epicenter. Все три опрашиваются параллельно,
результаты сливаются. Работает без API-ключей (HTML/JSON-LD парсинг).

Не выдумывает — если поиск пуст, возвращает пустой список.
"""
from __future__ import annotations
import re
import asyncio
import json
from html import unescape
from urllib.parse import quote_plus

import httpx
import structlog

log = structlog.get_logger()

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "uk,ru;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}


class ShopperClient:
    """Поиск товаров в 3 украинских магазинах параллельно."""

    async def search(
        self,
        query: str,
        max_price: int | None = None,
        category: str | None = None,
        limit: int = 6,
    ) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        # Параллельно опрашиваем все три магазина
        per_store = max(2, limit // 3 + 1)
        results = await asyncio.gather(
            self._search_rozetka(query, max_price, per_store),
            self._search_comfy(query, max_price, per_store),
            self._search_epicenter(query, max_price, per_store),
            return_exceptions=True,
        )
        merged: list[dict] = []
        for r in results:
            if isinstance(r, list):
                merged.extend(r)
        # Фильтр по цене (defensive — на случай если парсер не отсёк)
        if max_price:
            merged = [
                m for m in merged
                if not m.get("price_uah") or m["price_uah"] <= max_price
            ]
        # Дедуп по title (первым словам) — чтобы не показывать один товар из
        # разных магазинов если у обоих одинаковое имя
        seen: set[str] = set()
        unique: list[dict] = []
        for m in merged:
            key = m.get("title", "").lower()[:40]
            if key in seen:
                continue
            seen.add(key)
            unique.append(m)
        return unique[:limit]

    async def _fetch(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, timeout=12.0, follow_redirects=True
            ) as client:
                r = await client.get(url)
                r.raise_for_status()
                return r.text
        except Exception as e:
            log.warning("shopper_fetch_failed", url=url[:100], error=str(e)[:120])
            return None

    def _parse_jsonld_products(self, html: str, store: str, limit: int) -> list[dict]:
        """Общий fallback-парсер: ищет JSON-LD с schema.org/Product."""
        results: list[dict] = []
        # <script type="application/ld+json">...</script>
        for m in re.finditer(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        ):
            raw = m.group(1).strip()
            try:
                data = json.loads(raw)
            except Exception:
                continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                # ItemList → расширить
                if isinstance(item, dict) and item.get("@type") == "ItemList":
                    for elt in item.get("itemListElement", []):
                        obj = elt.get("item") if isinstance(elt, dict) else None
                        if obj:
                            candidates.append(obj)
                if not isinstance(item, dict):
                    continue
                if "Product" not in (item.get("@type") or ""):
                    continue
                title = (item.get("name") or "").strip()
                url = item.get("url") or (item.get("offers", {}).get("url") if isinstance(item.get("offers"), dict) else "")
                offers = item.get("offers")
                price = None
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                elif isinstance(offers, list) and offers:
                    price = offers[0].get("price") if isinstance(offers[0], dict) else None
                try:
                    price_num = int(float(price)) if price else None
                except Exception:
                    price_num = None
                if not title or not url:
                    continue
                results.append({
                    "title": title[:120],
                    "price_uah": price_num,
                    "price_raw": f"{price_num} грн" if price_num else "",
                    "url": url,
                    "store": store,
                })
                if len(results) >= limit:
                    return results
        return results

    async def _search_rozetka(
        self, query: str, max_price: int | None, limit: int
    ) -> list[dict]:
        url = f"https://rozetka.com.ua/ua/search/?text={quote_plus(query)}"
        if max_price:
            url += f"&price=0;{max_price}"
        html = await self._fetch(url)
        if not html:
            return []
        # Пробуем JSON-LD, потом goods-tile regex
        results = self._parse_jsonld_products(html, "Rozetka", limit)
        if results:
            log.info("shopper.rozetka", query=query[:60], found=len(results))
            return results
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
                "title": title[:120], "price_uah": price_num,
                "price_raw": price_raw, "url": link, "store": "Rozetka",
            })
            if len(results) >= limit:
                break
        log.info("shopper.rozetka", query=query[:60], found=len(results))
        return results

    async def _search_comfy(
        self, query: str, max_price: int | None, limit: int
    ) -> list[dict]:
        # Comfy: https://comfy.ua/ua/search/?q=...
        url = f"https://comfy.ua/ua/search/?q={quote_plus(query)}"
        if max_price:
            url += f"&price_max={max_price}"
        html = await self._fetch(url)
        if not html:
            return []
        results = self._parse_jsonld_products(html, "Comfy", limit)
        if results and max_price:
            results = [r for r in results if not r.get("price_uah") or r["price_uah"] <= max_price]
        log.info("shopper.comfy", query=query[:60], found=len(results))
        return results

    async def _search_epicenter(
        self, query: str, max_price: int | None, limit: int
    ) -> list[dict]:
        # Epicenter: https://epicentrk.ua/ua/search/?searchtext=...
        url = f"https://epicentrk.ua/ua/search/?searchtext={quote_plus(query)}"
        if max_price:
            url += f"&price_to={max_price}"
        html = await self._fetch(url)
        if not html:
            return []
        results = self._parse_jsonld_products(html, "Epicenter", limit)
        if results and max_price:
            results = [r for r in results if not r.get("price_uah") or r["price_uah"] <= max_price]
        log.info("shopper.epicenter", query=query[:60], found=len(results))
        return results
