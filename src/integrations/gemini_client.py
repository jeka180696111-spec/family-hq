"""Google Gemini API client — used as a text and tool-using fallback when
Anthropic is unavailable or when the user wants to save Claude credits.

Provides:
  - complete() — plain text, mirrors ClaudeClient.complete()
  - complete_with_tools() — function calling, mirrors
    ClaudeClient.complete_with_tools() by translating Claude's
    `input_schema` to Gemini's `functionDeclarations` and wrapping the
    response in Anthropic-compatible duck-typed Message/Block objects.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import aiohttp
import structlog

log = structlog.get_logger()


_MODEL_CANDIDATES = (
    # Lite first — higher free-tier quotas, fewer 429s under family usage
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
    # Then full flash variants (lower quota, often quota-exhausted on free tier)
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-002",
    "gemini-1.5-flash",
    # Pro variants last — tightest quota, but most capable
    "gemini-2.5-pro",
    "gemini-1.5-pro-latest",
    "gemini-1.5-pro-002",
    "gemini-1.5-pro",
)


async def discover_models(api_key: str) -> list[str]:
    """Call /v1beta/models to get the actual list this key can use."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    return []
                data = await resp.json()
    except Exception:
        log.exception("gemini_discover_failed")
        return []
    out = []
    for m in data.get("models") or []:
        name = (m.get("name") or "").replace("models/", "")
        methods = m.get("supportedGenerationMethods") or []
        if "generateContent" in methods and "gemini" in name:
            out.append(name)
    return out


# ─── Anthropic-shape duck types ─────────────────────────────────────────

class _TextBlock:
    type = "text"
    def __init__(self, text: str) -> None:
        self.text = text


class _ToolUseBlock:
    type = "tool_use"
    def __init__(self, name: str, tool_input: dict, block_id: str) -> None:
        self.name = name
        self.input = tool_input
        self.id = block_id


class _Usage:
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class _GeminiMessage:
    role = "assistant"
    def __init__(self, content: list, stop_reason: str, usage: _Usage) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash",
                 extra_keys: list[str] | None = None) -> None:
        # First key is the primary; extras are tried in order on
        # 429/403/permission errors (multi-account quota pooling).
        self.api_keys: list[str] = [api_key] + [k for k in (extra_keys or []) if k]
        self.api_key = api_key  # backward compat for callers reading .api_key
        self.model = (model or "").strip().replace("models/", "")
        self._working_model: str | None = None
        self._working_key_idx: int = 0

    @classmethod
    def from_settings(cls, settings: Any) -> "GeminiClient | None":
        key = getattr(settings, "gemini_api_key", "")
        model = getattr(settings, "gemini_model", "gemini-1.5-flash")
        extras_raw = getattr(settings, "gemini_api_keys", "") or ""
        extras = [k.strip() for k in extras_raw.split(",") if k.strip()]
        if not key:
            if not extras:
                return None
            key = extras.pop(0)
        return cls(key, model, extra_keys=extras)

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
            # Iterate keys × models. Stop at first success.
            for key_idx, key in enumerate(self.api_keys):
                for m in seen:
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/"
                        f"models/{m}:generateContent?key={key}"
                    )
                    try:
                        async with session.post(url, json=body) as resp:
                            if resp.status == 404:
                                last_err = f"key#{key_idx} {m}: not found"
                                continue
                            if resp.status in (429, 403):
                                last_err = f"key#{key_idx} {m}: HTTP {resp.status}"
                                # rotate key — likely quota/permission
                                break
                            if resp.status >= 400:
                                err = await resp.text()
                                last_err = f"key#{key_idx} {m}: HTTP {resp.status}: {err[:120]}"
                                continue
                            data = await resp.json()
                        self._working_model = m
                        self._working_key_idx = key_idx
                        try:
                            return data["candidates"][0]["content"]["parts"][0]["text"]
                        except (KeyError, IndexError):
                            log.warning("gemini_empty_response", model=m, payload=str(data)[:200])
                            return ""
                    except Exception as e:
                        last_err = f"key#{key_idx} {m}: {e}"
                        continue
        raise RuntimeError(f"Gemini: all keys×models failed. Last: {last_err[:200]}")

    # ─── Tool calling (Claude-compatible adapter) ─────────────────────

    @staticmethod
    def _translate_tools(claude_tools: list[dict]) -> list[dict]:
        """Convert Claude tool defs (`name`/`description`/`input_schema`)
        to Gemini function declarations."""
        decls = []
        for t in claude_tools or []:
            decls.append({
                "name": t.get("name", ""),
                "description": (t.get("description") or "")[:1024],
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            })
        return [{"functionDeclarations": decls}] if decls else []

    @staticmethod
    def _translate_messages_with_tools(messages: list[dict]) -> list[dict]:
        """Translate Claude-style message history (which may include
        tool_result blocks) to Gemini contents."""
        contents: list[dict] = []
        for m in messages or []:
            role = m.get("role", "user")
            gem_role = "user" if role == "user" else "model"
            content = m.get("content", "")
            if isinstance(content, str):
                contents.append({"role": gem_role, "parts": [{"text": content}]})
                continue
            parts = []
            for block in (content if isinstance(content, list) else []):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    parts.append({"text": block.get("text", "")})
                elif btype == "tool_use":
                    parts.append({"functionCall": {
                        "name": block.get("name", ""),
                        "args": block.get("input", {}) or {},
                    }})
                elif btype == "tool_result":
                    # Anthropic returns tool result with role=user in next turn
                    val = block.get("content", "")
                    if isinstance(val, list):
                        val = " ".join(
                            b.get("text", "") for b in val if isinstance(b, dict)
                        )
                    parts.append({"functionResponse": {
                        "name": block.get("tool_use_id", "tool")[:60],
                        "response": {"result": str(val)},
                    }})
            if parts:
                contents.append({"role": gem_role, "parts": parts})
        return contents

    async def complete_with_tools(
        self,
        model: str | None = None,
        system: str = "",
        messages: list[dict] | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 2048,
        **_: Any,
    ) -> _GeminiMessage:
        """Mimic ClaudeClient.complete_with_tools. Returns a duck-typed
        Message object so callers iterating over .content / .stop_reason
        work without changes."""
        contents = self._translate_messages_with_tools(messages or [])
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        gem_tools = self._translate_tools(tools or [])
        if gem_tools:
            body["tools"] = gem_tools

        seen: list[str] = []
        for m in (model, self._working_model, self.model, *_MODEL_CANDIDATES):
            if m and m not in seen:
                seen.append(m)

        last_err = "no models attempted"
        data = None
        async with aiohttp.ClientSession() as session:
            outer_break = False
            for key_idx, key in enumerate(self.api_keys):
                for m in seen:
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/"
                        f"models/{m}:generateContent?key={key}"
                    )
                    try:
                        async with session.post(url, json=body) as resp:
                            if resp.status == 404:
                                last_err = f"key#{key_idx} {m}: not found"
                                continue
                            if resp.status in (429, 403):
                                last_err = f"key#{key_idx} {m}: HTTP {resp.status}"
                                break  # rotate key
                            if resp.status >= 400:
                                err_text = await resp.text()
                                last_err = f"key#{key_idx} {m}: HTTP {resp.status}: {err_text[:120]}"
                                continue
                            data = await resp.json()
                        self._working_model = m
                        self._working_key_idx = key_idx
                        outer_break = True
                        break
                    except Exception as e:
                        last_err = f"key#{key_idx} {m}: {e}"
                        continue
                if outer_break:
                    break
            if data is None:
                raise RuntimeError(f"Gemini tool-use: {last_err[:200]}")

        # Translate Gemini response → Anthropic-shape Message
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        blocks: list = []
        has_tool_call = False
        for p in parts:
            if "text" in p:
                blocks.append(_TextBlock(p["text"]))
            elif "functionCall" in p:
                fc = p["functionCall"]
                blocks.append(_ToolUseBlock(
                    name=fc.get("name", ""),
                    tool_input=fc.get("args", {}) or {},
                    block_id=f"toolu_{uuid.uuid4().hex[:12]}",
                ))
                has_tool_call = True
        if not blocks:
            blocks.append(_TextBlock(""))
        stop_reason = "tool_use" if has_tool_call else "end_turn"
        usage_meta = data.get("usageMetadata") or {}
        usage = _Usage(
            input_tokens=usage_meta.get("promptTokenCount", 0),
            output_tokens=usage_meta.get("candidatesTokenCount", 0),
        )
        return _GeminiMessage(blocks, stop_reason, usage)
