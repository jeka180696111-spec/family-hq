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


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-exp") -> None:
        self.api_key = api_key
        self.model = model

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
        """Mimic ClaudeClient.complete signature. Returns plain text."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model or self.model}:generateContent?key={self.api_key}"
        )
        contents: list[dict] = []
        for m in messages or []:
            role = "user" if m.get("role") == "user" else "model"
            text = m.get("content", "")
            if isinstance(text, list):
                # Strip non-text blocks (we don't support images via Gemini here)
                text = " ".join(
                    b.get("text", "") for b in text if isinstance(b, dict) and b.get("type") == "text"
                )
            contents.append({"role": role, "parts": [{"text": str(text)}]})
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                if resp.status >= 400:
                    err = await resp.text()
                    raise RuntimeError(f"Gemini HTTP {resp.status}: {err[:200]}")
                data = await resp.json()

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            log.warning("gemini_empty_response", payload=str(data)[:300])
            return ""
