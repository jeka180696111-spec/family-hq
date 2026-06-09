"""Anthropic API client with primary/backup key failover and exponential backoff."""
from __future__ import annotations

import asyncio
from typing import Any

import anthropic
import structlog

log = structlog.get_logger()

_RETRYABLE_STATUS_CODES = {401, 429, 500, 502, 503}
_TIMEOUT_SECONDS = 30.0
_BACKOFF_BASE = 1.0  # seconds; doubled on each retry: 1s, 2s, 4s


class AIOfflineError(Exception):
    """Raised when both primary and backup API keys fail."""


class ClaudeClient:
    """
    Wrapper over anthropic.AsyncAnthropic with failover.

    Logic:
    1. Try via primary key.
    2. If 401/429/500/timeout — switch to backup key.
    3. If both fail — raise AIOfflineError.
    4. Exponential backoff on retries (1s, 2s, 4s).
    """

    def __init__(self, primary_key: str, backup_key: str) -> None:
        self._primary = anthropic.AsyncAnthropic(api_key=primary_key)
        self._backup = anthropic.AsyncAnthropic(api_key=backup_key)
        self._using_backup = False
        self._memory = None  # set later for usage logging

    def attach_memory(self, memory: Any) -> None:
        """Inject SharedMemory so usage rows can be persisted to api_usage."""
        self._memory = memory

    async def _log_usage(self, model: str, message: Any) -> None:
        if self._memory is None or message is None:
            return
        try:
            usage = getattr(message, "usage", None)
            if usage is None:
                return
            from datetime import date
            from sqlalchemy import insert
            from src.db.models import ApiUsage
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    insert(ApiUsage).values(
                        date=date.today().isoformat(),
                        agent_id=None,
                        model=model,
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "output_tokens", 0) or 0,
                        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                    )
                )
        except Exception:
            log.exception("usage_log_failed")

    async def complete(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        tools: list[dict] | None = None,
    ) -> str:
        """
        Send a completion request.

        Returns the text content of the first content block.
        On Anthropic outage (both primary+backup fail), falls back to
        Gemini for text-only responses if GEMINI_API_KEY is configured.
        """
        try:
            message = await self._complete_with_failover(
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                tools=tools,
            )
        except AIOfflineError:
            # Try Gemini as text fallback (no tool support)
            try:
                from src.config import get_settings
                from src.integrations.gemini_client import GeminiClient
                gemini = GeminiClient.from_settings(get_settings())
                if gemini and not tools:
                    log.warning("claude_fallback_to_gemini")
                    return await gemini.complete(
                        system=system, messages=messages, max_tokens=max_tokens,
                    )
            except Exception:
                log.exception("gemini_fallback_failed")
            raise
        first_block = message.content[0]
        return first_block.text if hasattr(first_block, "text") else str(first_block)

    async def complete_with_tools(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 2048,
    ) -> anthropic.types.Message:
        """
        Send a request that may involve tool use.

        Returns the full Message object.
        """
        return await self._complete_with_failover(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
        )

    async def _complete_with_failover(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tools: list[dict] | None,
    ) -> anthropic.types.Message:
        """Attempt completion with primary key; fall back to backup on failure."""
        clients = [
            ("primary", self._primary),
            ("backup", self._backup),
        ]
        last_exc: Exception | None = None

        for attempt_index, (key_label, client) in enumerate(clients):
            delay = _BACKOFF_BASE
            for retry in range(3):  # up to 3 retries per client
                try:
                    message = await self._try_complete(
                        client=client,
                        model=model,
                        system=system,
                        messages=messages,
                        max_tokens=max_tokens,
                        tools=tools,
                    )
                    if attempt_index == 1:
                        self._using_backup = True
                        log.info("claude_using_backup_key")
                    await self._log_usage(model, message)
                    return message

                except (anthropic.APIStatusError, anthropic.APIConnectionError, asyncio.TimeoutError) as exc:
                    last_exc = exc
                    retryable = True
                    if isinstance(exc, anthropic.APIStatusError):
                        retryable = exc.status_code in _RETRYABLE_STATUS_CODES

                    log.warning(
                        "claude_request_failed",
                        key=key_label,
                        retry=retry,
                        error=str(exc),
                        retryable=retryable,
                    )

                    if not retryable:
                        break

                    if retry < 2:
                        await asyncio.sleep(delay)
                        delay *= 2

            # Exhausted retries for this client; switch to backup
            if attempt_index == 0:
                log.warning(
                    "claude_switching_to_backup",
                    reason=str(last_exc),
                )

        raise AIOfflineError(
            f"Both primary and backup API keys failed. Last error: {last_exc}"
        ) from last_exc

    async def _try_complete(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int,
        tools: list[dict] | None,
    ) -> anthropic.types.Message:
        """Internal: attempt a single completion with a specific client."""
        # Prompt caching: large stable system prompts → cache for 5 min.
        # Saves ~90% on input tokens for cached portion.
        system_payload: Any = system
        if isinstance(system, str) and len(system) > 1024:
            system_payload = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        kwargs: dict[str, Any] = {
            "model": model,
            "system": system_payload,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            # Tools are also a stable part — cache them by marking the last tool
            kwargs["tools"] = [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}] if tools else tools

        return await asyncio.wait_for(
            client.messages.create(**kwargs),
            timeout=_TIMEOUT_SECONDS,
        )

    @property
    def is_using_backup(self) -> bool:
        return self._using_backup
