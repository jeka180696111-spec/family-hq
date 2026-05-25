"""Web search client for the Gurman (cook) agent — recipe and nutrition lookup."""
from __future__ import annotations

import asyncio
import re
from html import unescape

import httpx
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
}


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchClient:
    """
    Simple web search for finding recipes and nutritional info.

    Uses DuckDuckGo HTML search (no API key needed) as the primary backend.
    All methods are safe to call without ``try``/``except`` — failures are
    logged and the caller receives an empty list or empty string.
    """

    async def search(
        self, query: str, max_results: int = 5
    ) -> list[SearchResult]:
        """
        Search the web and return up to *max_results* results.

        Never raises — returns an empty list on any failure.
        """
        try:
            return await asyncio.wait_for(
                self._ddg_search(query, max_results),
                timeout=10.0,
            )
        except Exception:
            log.warning("web_search_failed", query=query)
            return []

    async def _ddg_search(
        self, query: str, max_results: int
    ) -> list[SearchResult]:
        """DuckDuckGo HTML search — scrapes the lite HTML endpoint."""
        async with httpx.AsyncClient(
            follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = await client.post(
                _DDG_URL,
                data={"q": query, "kl": "ru-ru"},
                timeout=9.0,
            )
            resp.raise_for_status()
            html = resp.text

        results: list[SearchResult] = []

        # Each result block is wrapped in <div class="result ...">
        # Extract title, URL and snippet with lightweight regex rather than
        # a full HTML parser to avoid an extra dependency.
        result_blocks = re.findall(
            r'class="result__title".*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for raw_url, raw_title, raw_snippet in result_blocks:
            url = unescape(raw_url).strip()
            title = unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            snippet = unescape(re.sub(r"<[^>]+>", "", raw_snippet)).strip()

            if not url.startswith("http"):
                continue

            results.append(SearchResult(title=title, url=url, snippet=snippet))
            if len(results) >= max_results:
                break

        log.debug("web_search_done", query=query, returned=len(results))
        return results

    async def fetch_page_text(self, url: str, max_chars: int = 3000) -> str:
        """
        Fetch a URL and return its plain-text content (up to *max_chars*).

        Strips all HTML tags and collapses whitespace.  Returns an empty
        string on any failure.
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, headers=_HEADERS
            ) as client:
                resp = await client.get(url, timeout=10.0)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            log.warning("fetch_page_text_failed", url=url, error=str(exc))
            return ""

        # Remove script / style blocks entirely
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Strip remaining tags
        text = re.sub(r"<[^>]+>", " ", html)
        # Decode HTML entities and collapse whitespace
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()

        truncated = text[:max_chars]
        log.debug("fetch_page_text_done", url=url, chars=len(truncated))
        return truncated
