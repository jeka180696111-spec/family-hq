"""Google Gemini API client — used as a text fallback when Anthropic is
unavailable (no credits, outage, rate limit).

Scope: text completion only via .complete(). Tool calling is NOT
translated — when Claude is down, agents lose tool use until it
recovers. Health pings, parsing, dispatching and short text replies
still work, so the system stays alive in degraded mode.
"""
from __future__ import annotations

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()


# Models to try in order if the preferred one is rejected. Newer first,
# so we automatically pick up upgrades as Google promotes them; falls
# back to the proven-stable 1.5-flash.
_MODEL_CANDIDATES = (
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
)


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        self.api_key = api_key
        self.model = model
        self._working_model: str | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> "GeminiClient | None":
        key = getattr(settings, "gemini_api_key", "")
        model = getattr(settings, "gemini_model", "gemini-2.0-flash-exp")
        if not key:
            return None
        return cls(key, model)

    async def complete(
        self,
        model: str | None = None,
        system: str = "",
        messages: list[dict] | None = None,
        max_tokens: int = 1024,
        **_: Any,
    ) -> str:
        """Mimic ClaudeClient.complete. Tries configured model first;
        on 404 (model deprecated/renamed) falls through the candidate
        list and caches the first model that responds."""
        contents: list[dict] = []
        for m in messages or []:
            role = "user" if m.get("role") == "user" else "model"
            text = m.get("content", "")
            if isinstance(text, list):
                text = " ".join(
                    b.get("text", "") for b in text
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            contents.append({"role": role, "parts": [{"text": str(text)}]})
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        # Build the try-order: caller-provided > cached working > configured > candidates
        seen: list[str] = []
        for m in (model, self._working_model, self.model, *_MODEL_CANDIDATES):
            if m and m not in seen:
                seen.append(m)

        last_err = "no models attempted"
        async with aiohttp.ClientSession() as session:
            for m in seen:
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/"
                    f"models/{m}:generateContent?key={self.api_key}"
                )
                try:
                    async with session.post(url, json=body) as resp:
                        if resp.status == 404:
                            last_err = f"{m}: model not found"
                            log.info("gemini_model_skip", model=m)
                            continue
                        if resp.status >= 400:
                            err = await resp.text()
                            last_err = f"{m}: HTTP {resp.status}: {err[:120]}"
                            continue
                        data = await resp.json()
                    self._working_model = m
                    try:
                        return data["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError):
                        log.warning("gemini_empty_response", model=m, payload=str(data)[:200])
                        return ""
                except Exception as e:
                    last_err = f"{m}: {e}"
                    continue
        raise RuntimeError(f"Gemini: all models failed. Last error: {last_err[:200]}")
