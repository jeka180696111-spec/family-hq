"""Shopper — поиск товаров через DuckDuckGo с фильтром по украинским магазинам.

Вместо парсинга HTML магазинов (не работает — Cloudflare, JS-рендер),
используем DuckDuckGo с site-фильтром. Возвращаем title/url/snippet;
Butler LLM синтезирует ответ юзеру.
"""
from __future__ import annotations
import structlog

log = structlog.get_logger()

_STORE_DOMAINS = [
    ("rozetka.com.ua", "Rozetka"),
    ("comfy.ua", "Comfy"),
    ("epicentrk.ua", "Epicenter"),
    ("prom.ua", "Prom"),
    ("olx.ua", "OLX"),
    ("allo.ua", "Allo"),
    ("foxtrot.com.ua", "Foxtrot"),
]


def _store_from_url(url: str) -> str:
    low = (url or "").lower()
    for domain, name in _STORE_DOMAINS:
        if domain in low:
            return name
    # Отбрасываем не-магазины
    return ""


class ShopperClient:
    """Ищет через DuckDuckGo с фильтром site:<магазин>. Без API-ключей."""

    def __init__(self, web_search=None) -> None:
        # Ленивая инициализация — WebSearchClient создаётся при первом вызове
        self._web = web_search

    def _get_web(self):
        if self._web is None:
            from src.integrations.web_search import WebSearchClient
            self._web = WebSearchClient()
        return self._web

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

        # Собираем site-фильтр для DuckDuckGo
        sites = " OR ".join(f"site:{d}" for d, _ in _STORE_DOMAINS[:5])
        search_query = f"{query} ({sites})"
        # Если указан бюджет, добавляем ориентир в текст запроса
        if max_price:
            search_query = f"{query} до {max_price} грн ({sites})"

        web = self._get_web()
        try:
            raw = await web.search(search_query, max_results=limit * 2)
        except Exception as e:
            log.warning("shopper_web_search_failed", error=str(e)[:120])
            raw = []

        results: list[dict] = []
        for item in (raw or []):
            # WebSearchClient.search возвращает SearchResult (title, url, snippet)
            title = getattr(item, "title", None) or (item.get("title") if isinstance(item, dict) else "")
            url = getattr(item, "url", None) or (item.get("url") if isinstance(item, dict) else "")
            snippet = getattr(item, "snippet", None) or (item.get("snippet") if isinstance(item, dict) else "")
            if not title or not url:
                continue
            store = _store_from_url(url)
            if not store:
                continue  # только результаты из известных магазинов
            results.append({
                "title": (title or "").strip()[:140],
                "url": url,
                "snippet": (snippet or "").strip()[:200],
                "store": store,
            })
            if len(results) >= limit:
                break

        log.info("shopper.search", query=query[:60], found=len(results))
        # Если ничего не нашлось — вернуть прямые ссылки на поиск в магазинах
        if not results:
            from urllib.parse import quote_plus
            q = quote_plus(query)
            return [
                {"title": f"Rozetka — поиск «{query}»", "url": f"https://rozetka.com.ua/ua/search/?text={q}",
                 "snippet": "", "store": "Rozetka", "is_search_link": True},
                {"title": f"Comfy — поиск «{query}»", "url": f"https://comfy.ua/ua/search/?q={q}",
                 "snippet": "", "store": "Comfy", "is_search_link": True},
                {"title": f"Epicenter — поиск «{query}»", "url": f"https://epicentrk.ua/ua/search/?searchtext={q}",
                 "snippet": "", "store": "Epicenter", "is_search_link": True},
            ]
        return results
