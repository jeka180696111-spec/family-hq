"""Baby sleep window predictor.

Every few minutes computes Matvey's current state from the Дневник
sheet, calculates how long he's been awake, and — if approaching the
age-typical wake window minus a soft warning — pushes Marina/Eugene
«🍼 Матвейка скоро устанет, замедляйся».

Idempotent: each awake cycle gets at most one warning.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

log = structlog.get_logger()


# Wake-window typical for healthy babies, in minutes.
# Source: standard pediatric guidance (Marc Weissbluth, AAP).
# Keys are upper-bound age in months; matches first whose age_months ≤ key.
_WAKE_WINDOWS_MIN = [
    (1,  60),
    (2,  85),
    (3,  90),
    (4,  105),
    (6,  120),
    (9,  150),   # 6-9 mo: 2h15-2h30 ← Матвей сейчас здесь
    (12, 195),
    (18, 240),
    (36, 330),
]


def _expected_wake_window_min(age_months: float) -> int:
    for upper, mins in _WAKE_WINDOWS_MIN:
        if age_months <= upper:
            return mins
    return 330


class SleepPredictor:
    """Runs on a cron tick. Holds the last-pushed timestamp so we don't
    spam (one warning per awake cycle)."""

    _LEAD_WARNING_MIN = 15

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
        self._last_warning_for_awake_since: str | None = None
        # «пора будить» — идемпотентность по sleeping_since, чтобы не
        # спамить каждые 5 мин пока ребёнок спит.
        self._last_wake_alert_for_sleeping_since: str | None = None

    async def tick(self) -> None:
        # Не вклиниваться когда юзер активно пишет в чат.
        try:
            from src.utils.chat_activity import is_chat_active
            if is_chat_active(within_seconds=90):
                return
        except Exception:
            pass
        try:
            from src.integrations.baby_state_compute import compute_state_from_diary
            from src.utils.family import CHILD
            from src.utils.time import now_kyiv

            sheets = getattr(self._nanny, "_sheets", None)
            if not sheets:
                return
            state = await compute_state_from_diary(sheets)
            awake_since_iso = state.get("awake_since")
            sleeping_since_iso = state.get("sleeping_since")

            # ── Если Матвей сейчас СПИТ → проверяем «пора будить» ────
            if sleeping_since_iso:
                await self._maybe_wake_alert(sleeping_since_iso)
                return
            if not awake_since_iso:
                return

            if awake_since_iso == self._last_warning_for_awake_since:
                return

            awake_since = datetime.fromisoformat(awake_since_iso)
            now = now_kyiv()
            awake_min = (now - awake_since).total_seconds() / 60.0
            if awake_min < 30:
                return

            # Тихий час 23:00-06:00 — длинный ночной сон, не пушим.
            if now.hour >= 23 or now.hour < 6:
                return

            birth = CHILD.get("birth_date")
            if not birth:
                return
            age_days = (now.date() - birth).days
            age_months = age_days / 30.4375

            # Personalised window — берём средний реальный wake window
            # Матвея за последние 14д. Если данных мало, fallback на
            # возрастную норму.
            from src.integrations.sleep_coach import (
                personal_baseline, _personalised_window_min,
            )
            baseline = await personal_baseline(sheets, days=30)
            window_min, window_src = _personalised_window_min(baseline, age_months)

            until_window = window_min - awake_min
            if not (-5 <= until_window <= self._LEAD_WARNING_MIN):
                return

            from src.integrations.sleep_coach import _fmt_hm
            if until_window > 0:
                text = (
                    "🍼 <b>Матвейка скоро устанет</b>\n"
                    f"Бодрствует уже {_fmt_hm(awake_min)}. Его обычное окно — "
                    f"~{_fmt_hm(window_min)} ({window_src}), осталось ~{_fmt_hm(until_window)}. "
                    "Замедляйся, приглуши свет, готовь к укладыванию."
                )
            else:
                text = (
                    "🍼 <b>Перегул</b>\n"
                    f"Матвей бодрствует {_fmt_hm(awake_min)} — обычное окно "
                    f"~{_fmt_hm(window_min)} ({window_src}). Чем дальше, тем "
                    "сложнее будет уложить. Пора."
                )

            try:
                await self._bots.send_message(
                    agent_id="nanny", chat_id=self._chat_id, text=text,
                )
                self._last_warning_for_awake_since = awake_since_iso
                log.info(
                    "sleep_warning_pushed",
                    awake_min=int(awake_min), window_min=window_min,
                    age_months=round(age_months, 2),
                )
            except Exception:
                log.exception("sleep_warning_push_failed")
        except Exception:
            log.exception("sleep_predictor_tick_failed")


    async def _maybe_wake_alert(self, sleeping_since_iso: str) -> None:
        """If Matvey has been sleeping past the age-typical nap length
        (or any nap continuing past 17:00) — нужен пуш «пора будить»,
        чтобы не съесть ночной сон. Один пуш на цикл сна."""
        if sleeping_since_iso == self._last_wake_alert_for_sleeping_since:
            return
        from src.utils.time import now_kyiv
        from src.utils.family import CHILD
        sleeping_since = datetime.fromisoformat(sleeping_since_iso)
        now = now_kyiv()
        slept_min = (now - sleeping_since).total_seconds() / 60.0

        birth = CHILD.get("birth_date")
        if not birth:
            return
        age_months = (now.date() - birth).days / 30.4375

        # Personalised nap target — реальная средняя длина дневного
        # сна Матвея. Fallback на возраст если данных недостаточно.
        from src.integrations.sleep_coach import (
            personal_baseline, _personalised_nap_target,
        )
        sheets = getattr(self._nanny, "_sheets", None)
        if sheets:
            baseline = await personal_baseline(sheets, days=30)
            target, target_src = _personalised_nap_target(baseline, age_months)
        else:
            target = 90
            target_src = "запасной вариант"

        # Night check — 21:00-06:00: уже фактически вечер/bedtime,
        # не лезем с «пора будить». Пусть спит.
        if now.hour >= 21 or now.hour < 6:
            return

        # Не пушить «пора будить» через 2 минуты после засыпания.
        # Минимум 30 мин фактического сна.
        if slept_min < 30:
            return

        # Окно бодрствования по возрасту — для 6 мес это 1.5-2ч,
        # никак не 3-4ч (это было моим багом, гнусным).
        if age_months <= 6:
            ww_hint = "1.5-2ч"
        elif age_months <= 9:
            ww_hint = "2-2.5ч"
        elif age_months <= 15:
            ww_hint = "2.5-3ч"
        else:
            ww_hint = "3-4ч"

        # Триггеры пуша:
        # 1) Спит больше target+20 мин — перебрал.
        # 2) Уже 18:00+ — сон в это время крадёт ночь.
        late_nap = now.hour >= 18
        overslept = slept_min > target + 20

        if not (late_nap or overslept):
            return

        from src.integrations.sleep_coach import _fmt_hm
        if overslept:
            text = (
                f"⏰ <b>Пора будить</b>\n"
                f"Матвей спит уже {_fmt_hm(slept_min)} — это {_fmt_hm(slept_min - target)} "
                f"сверх его обычного дневного сна (~{_fmt_hm(target)}, {target_src}). "
                f"Если оставить — украдёт ночь."
            )
        else:
            text = (
                f"⏰ <b>Пора будить</b>\n"
                f"Сейчас {now.strftime('%H:%M')}, Матвей спит {_fmt_hm(slept_min)}. "
                f"Сон в это время сильно бьёт по ночному. Лучше разбудить "
                f"и держать бодрствование ~{ww_hint} до bedtime."
            )

        try:
            await self._bots.send_message(
                agent_id="nanny", chat_id=self._chat_id, text=text,
            )
            self._last_wake_alert_for_sleeping_since = sleeping_since_iso
            log.info(
                "wake_alert_pushed",
                slept_min=int(slept_min), target=target,
                hour=now.hour,
            )
        except Exception:
            log.exception("wake_alert_push_failed")


def register_sleep_predictor_job(scheduler, predictor: SleepPredictor) -> None:
    scheduler.add_job(
        predictor.tick, "interval", minutes=5,
        id="sleep_predictor", replace_existing=True,
    )
    log.info("sleep_predictor_registered")
