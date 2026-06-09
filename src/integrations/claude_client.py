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


# Module-level tracking of which AI provider was used last and how many times.
# Read by the devops ai_status tool and the dashboard.
_AI_STATS: dict = {
    "current_provider": "claude",
    "last_model": None,        # last model name (Sonnet / Haiku / Gemini-...)
    "last_call_at": None,
    "claude_count": 0,
    "gemini_count": 0,
    "claude_fail_count": 0,
    "gemini_fail_count": 0,
    "override_provider": None,
    "override_until": None,
}


def get_ai_stats() -> dict:
    return dict(_AI_STATS)


def _record_call(provider: str, ok: bool, model: str | None = None) -> None:
    from src.utils.time import iso_now
    if ok:
        _AI_STATS[f"{provider}_count"] += 1
        _AI_STATS["current_provider"] = provider
        if model:
            _AI_STATS["last_model"] = model
    else:
        _AI_STATS[f"{provider}_fail_count"] += 1
    _AI_STATS["last_call_at"] = iso_now()


def signature_emoji() -> str:
    """Returns the emoji that identifies the AI which produced the last
    successful completion. Append to agent reply so the user can see
    at a glance which model is talking.

      🟦  Claude Sonnet (premium, paid)
      🟩  Claude Haiku  (cheap Claude)
      🟨  Gemini        (free Google fallback)
    """
    prov = _AI_STATS.get("current_provider", "claude")
    model = (_AI_STATS.get("last_model") or "").lower()
    if prov == "gemini":
        return "🟨"
    if "haiku" in model:
        return "🟩"
    return "🟦"


def set_provider_override(provider: str | None, until_iso: str | None = None) -> dict:
    """Force-route subsequent completes through `provider` until
    `until_iso` (Kyiv-local) passes. Pass provider=None to clear.

    Persists to family_overrides table so Railway restarts don't wipe it.
    """
    if provider not in (None, "claude", "gemini"):
        return {"error": "provider must be 'claude', 'gemini', or null"}
    _AI_STATS["override_provider"] = provider
    _AI_STATS["override_until"] = until_iso

    # Persist (best-effort, sync DB write via separate engine to avoid
    # async/event-loop conflicts from sync caller contexts)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_persist_override(provider, until_iso))
    except Exception:
        pass

    return {
        "override_provider": provider,
        "override_until": until_iso,
    }


async def _persist_override(provider: str | None, until_iso: str | None) -> None:
    try:
        from sqlalchemy import select, delete, insert
        from src.db.models import FamilyOverride
        from src.db.migrations import init_db
        from src.utils.time import iso_now
        engine = await init_db()
        async with engine.begin() as conn:
            await conn.execute(delete(FamilyOverride).where(
                FamilyOverride.key.in_(("ai.override_provider", "ai.override_until"))
            ))
            now = iso_now()
            if provider:
                await conn.execute(insert(FamilyOverride).values(
                    key="ai.override_provider", value=provider,
                    updated_at=now,
                ))
            if until_iso:
                await conn.execute(insert(FamilyOverride).values(
                    key="ai.override_until", value=until_iso,
                    updated_at=now,
                ))
    except Exception:
        log.exception("ai_override_persist_failed")


def load_override_from_overrides(overrides: dict) -> None:
    """Read persisted override from the family_overrides dict (loaded by
    main on startup). Call after apply_overrides so module state matches DB."""
    prov = overrides.get("ai.override_provider")
    until = overrides.get("ai.override_until")
    if prov:
        _AI_STATS["override_provider"] = prov
    if until:
        _AI_STATS["override_until"] = until


def _override_active() -> str | None:
    prov = _AI_STATS.get("override_provider")
    if not prov:
        return None
    until = _AI_STATS.get("override_until")
    if until:
        try:
            from datetime import datetime
            from src.utils.time import KYIV_TZ, now_kyiv
            t = datetime.fromisoformat(until)
            if t.tzinfo is None:
                t = t.replace(tzinfo=KYIV_TZ)
            if now_kyiv() >= t:
                # Expired — clear and return None
                _AI_STATS["override_provider"] = None
                _AI_STATS["override_until"] = None
                return None
        except Exception:
            return prov
    return prov




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
        # Manual override — force Gemini path if user requested it
        if _override_active() == "gemini" and not tools:
            try:
                from src.config import get_settings
                from src.integrations.gemini_client import GeminiClient
                gemini = GeminiClient.from_settings(get_settings())
                if gemini:
                    text = await gemini.complete(
                        system=system, messages=messages, max_tokens=max_tokens,
                    )
                    _record_call("gemini", ok=True, model="gemini")
                    return text
            except Exception:
                _record_call("gemini", ok=False)
                log.exception("gemini_override_failed_fallback_to_claude")
        try:
            message = await self._complete_with_failover(
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                tools=tools,
            )
        except AIOfflineError:
            _record_call("claude", ok=False)
            try:
                from src.config import get_settings
                from src.integrations.gemini_client import GeminiClient
                gemini = GeminiClient.from_settings(get_settings())
                if gemini and not tools:
                    log.warning("claude_fallback_to_gemini")
                    try:
                        text = await gemini.complete(
                            system=system, messages=messages, max_tokens=max_tokens,
                        )
                        _record_call("gemini", ok=True)
                        return text
                    except Exception:
                        _record_call("gemini", ok=False)
                        raise
            except Exception:
                log.exception("gemini_fallback_failed")
            raise
        _record_call("claude", ok=True, model=model)
        first_block = message.content[0]
        return first_block.text if hasattr(first_block, "text") else str(first_block)

    async def complete_with_tools(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 2048,
    ) -> Any:
        """
        Send a request that may involve tool use.

        Returns the full Message object (anthropic.types.Message OR a
        Gemini duck-typed adapter when the user's override is active /
        Claude is unavailable).
        """
        # Manual override — route through Gemini if user requested it
        if _override_active() == "gemini":
            try:
                from src.config import get_settings
                from src.integrations.gemini_client import GeminiClient
                gemini = GeminiClient.from_settings(get_settings())
                if gemini:
                    msg = await gemini.complete_with_tools(
                        system=system, messages=messages,
                        tools=tools, max_tokens=max_tokens,
                    )
                    _record_call("gemini", ok=True, model="gemini")
                    return msg
            except Exception as e:
                _record_call("gemini", ok=False)
                _AI_STATS["last_gemini_error"] = str(e)[:200]
                log.exception("gemini_tool_override_failed_fallback_to_claude")
        try:
            result = await self._complete_with_failover(
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                tools=tools,
            )
            _record_call("claude", ok=True, model=model)
            return result
        except AIOfflineError:
            _record_call("claude", ok=False)
            # Auto-fallback to Gemini on Anthropic outage
            try:
                from src.config import get_settings
                from src.integrations.gemini_client import GeminiClient
                gemini = GeminiClient.from_settings(get_settings())
                if gemini:
                    log.warning("claude_fallback_to_gemini_with_tools")
                    msg = await gemini.complete_with_tools(
                        system=system, messages=messages,
                        tools=tools, max_tokens=max_tokens,
                    )
                    _record_call("gemini", ok=True, model="gemini")
                    return msg
            except Exception:
                log.exception("gemini_tool_fallback_failed")
            raise

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
