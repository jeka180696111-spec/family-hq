"""Reactive sleep watcher.

Every 2 minutes scans the Дневник for new sleep entries (start/end).
When a fresh row appears that we haven't seen before, Няня reacts in
chat: «уснул в 12:15, как планировали → проснётся около 13:30», etc.

Uses a small in-memory set of seen row signatures so we don't
double-comment on the same entry. On process restart the set is empty —
we backfill recent rows quietly without commenting (so a deploy doesn't
spam old entries).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger()


class SleepReactor:
    # How far back to scan for new entries on each tick.
    _LOOKBACK_MIN = 30

    def __init__(
        self,
        memory: Any,
        nanny_agent: Any,
        bot_manager: Any,
        chat_id: int,
    ) -> None:
        self._memory = memory
        self._nanny = nanny_agent
        self._bots = bot_manager
        self._chat_id = chat_id
        self._seen: set[str] = set()
        self._primed = False  # First tick after startup: backfill, don't comment

    def _sig(self, row_data: dict) -> str:
        return f"{row_data.get('date','')}|{row_data.get('time','')}|{(row_data.get('event','') or '').lower()[:40]}"

    async def tick(self) -> None:
        try:
            from src.integrations.sleep_coach import (
                _parse_entry_dt, _kind_clean, _is_start, _is_end,
                next_sleep_advice,
            )
            from src.utils.time import now_kyiv

            sheets = getattr(self._nanny, "_sheets", None)
            if not sheets:
                return
            rows = await sheets.get_baby_diary(days=1)
            now = now_kyiv()
            cutoff = now - timedelta(minutes=self._LOOKBACK_MIN)

            fresh: list[dict] = []
            for r in rows:
                d = r.data
                if _kind_clean(d.get("kind", "")) not in ("сон", "sleep"):
                    continue
                dt = _parse_entry_dt(d)
                if dt is None or dt < cutoff:
                    # Still mark as seen to avoid commenting if it's
                    # re-edited; but не считаем fresh.
                    self._seen.add(self._sig(d))
                    continue
                sig = self._sig(d)
                if sig in self._seen:
                    continue
                self._seen.add(sig)
                ev = (d.get("event") or "").strip()
                kind_evt = "start" if _is_start(ev) else "end" if _is_end(ev) else "ambiguous"
                fresh.append({"dt": dt, "event": ev, "kind": kind_evt})

            # First tick after startup: don't react to anything we just
            # saw — those entries existed BEFORE our process came up.
            if not self._primed:
                self._primed = True
                return
            if not fresh:
                return

            # Take the freshest event only — if Marina logged two within
            # the lookback window, the latest one drives the comment.
            fresh.sort(key=lambda x: x["dt"], reverse=True)
            ev = fresh[0]
            if ev["kind"] == "ambiguous":
                return

            advice = await next_sleep_advice(sheets)

            if ev["kind"] == "start":
                base = f"Записал: уснул в {ev['dt'].strftime('%H:%M')}."
            else:
                base = f"Записал: проснулся в {ev['dt'].strftime('%H:%M')}."

            adv_text = (advice or {}).get("summary_for_agent", "")
            prompt = (
                f"Маринa только что внесла в Дневник: «{ev['event']}» в "
                f"{ev['dt'].strftime('%H:%M')}.\n\n"
                f"{base}\n\nКонтекст по текущему состоянию для совета:\n{adv_text}\n\n"
                "Напиши КОРОТКОЕ (1-3 строки) сообщение Марине в чат. "
                "Тёплый, человечный тон. Без сюсюканья, без 🤱 и 💕. "
                "Если уснул — подскажи когда планируется пробуждение. "
                "Если проснулся — скажи сколько до следующего сна. "
                "Не повторяй очевидное, не цитируй её сообщение. "
                "Можно одну деталь про то что советовала Няня раньше "
                "(«как и собирались» / «чуть позже плана»)."
            )
            try:
                text = await self._nanny._claude.complete(
                    model=self._nanny._get_model(),
                    system="Ты — Няня. Реактивный комментарий после записи о сне.",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                )
            except Exception:
                log.exception("sleep_reactor_llm_failed")
                return
            text = (text or "").strip()
            if not text:
                return
            try:
                await self._bots.send_message(
                    agent_id="nanny", chat_id=self._chat_id, text=text,
                )
                log.info("sleep_reactor_commented", kind=ev["kind"], event=ev["event"][:40])
            except Exception:
                log.exception("sleep_reactor_send_failed")
        except Exception:
            log.exception("sleep_reactor_tick_failed")


def register_sleep_reactor_job(scheduler, reactor: SleepReactor) -> None:
    scheduler.add_job(
        reactor.tick, "interval", minutes=2,
        id="sleep_reactor", replace_existing=True,
    )
    log.info("sleep_reactor_registered")
