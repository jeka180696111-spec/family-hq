"""Voice → text transcription via OpenAI Whisper API.

Why Whisper:
- Multilingual including RU + UK out of the box
- ~$0.006/min, 1-min voice ≈ $0.0001
- No GPU needed locally, simple HTTP call
"""
from __future__ import annotations

from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()


class TranscribeClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_settings(cls, settings: Any) -> "TranscribeClient | None":
        key = getattr(settings, "openai_api_key", None)
        return cls(key) if key else None

    async def transcribe(self, local_path: str, language: str | None = None) -> str:
        """Send the audio file to Whisper and return raw text."""
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = aiohttp.FormData()
        data.add_field("model", "whisper-1")
        if language:
            data.add_field("language", language)
        # Hint Whisper that the audio is Russian/Ukrainian to bias decoder
        data.add_field("prompt", "Семейный чат на русском и украинском. Имена: Матвей, Марина, Евгений.")
        with open(local_path, "rb") as f:
            audio_bytes = f.read()
        data.add_field(
            "file", audio_bytes,
            filename=local_path.rsplit("/", 1)[-1] or "voice.ogg",
            content_type="audio/ogg",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise RuntimeError(f"Whisper HTTP {resp.status}: {body[:200]}")
                result = await resp.json()
        return (result.get("text") or "").strip()
