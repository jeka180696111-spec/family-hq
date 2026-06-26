"""Sleep-coach helpers: analyse Matvey's Дневник entries and produce
both a weekly summary and a «what to do now» recommendation.

Pediatric reference: standard age-typical wake windows (Weissbluth /
Ferber). Numbers below are conservative midpoints — Няня всегда подаёт
их как ориентир, не как догму.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


_WAKE_WINDOWS_MIN = [
    (1,  60),
    (2,  85),
    (3,  90),
    (4,  105),
    (6,  120),
    (9,  150),
    (12, 195),
    (18, 240),
    (36, 330),
]

# Number of daytime naps appropriate for age in months.
_DAYTIME_NAPS = [
    (3,  "4-5"),
    (5,  "3-4"),
    (8,  "3"),
    (15, "2"),
    (36, "1"),
]

# Typical total sleep per 24h (lower-upper) by age in months.
_TOTAL_SLEEP_HOURS = [
    (3,  (14, 17)),
    (6,  (13, 16)),
    (9,  (12, 15)),
    (12, (12, 14)),
    (18, (11, 14)),
    (36, (10, 13)),
]


def _pick(table: list[tuple[int, Any]], age_months: float) -> Any:
    for upper, val in table:
        if age_months <= upper:
            return val
    return table[-1][1]


def expected_wake_window_min(age_months: float) -> int:
    return _pick(_WAKE_WINDOWS_MIN, age_months)


def expected_daytime_naps(age_months: float) -> str:
    return _pick(_DAYTIME_NAPS, age_months)


def expected_total_sleep_hours(age_months: float) -> tuple[int, int]:
    return _pick(_TOTAL_SLEEP_HOURS, age_months)


def _fmt_hm(minutes: float) -> str:
    if minutes < 0:
        return "—"
    h = int(minutes // 60)
    m = int(minutes % 60)
    return f"{h}ч {m:02d}м" if h else f"{m}м"


def _parse_entry_dt(row_data: dict):
    from src.utils.time import KYIV_TZ
    date_s = (row_data.get("date") or "").strip()
    time_s = (row_data.get("time") or "00:00").strip()
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{date_s} {time_s}", fmt).replace(tzinfo=KYIV_TZ)
        except ValueError:
            continue
    return None


def _kind_clean(cell: str) -> str:
    cleaned = cell or ""
    for ch in cell or "":
        if ch.isalpha():
            break
        cleaned = cleaned[1:]
    return cleaned.strip().lower()


_SLEEP_START_WORDS = (
    "уснул", "уснула", "заснул", "лёг", "лег", "начал спать", "пошёл спать",
    "пошел спать", "укладыва", "отбой", "уложила", "уложил",
)
_SLEEP_END_WORDS = (
    "проснул", "встал", "разбудил", "просыпан", "не спит", "подъём", "подьем",
)


def _is_start(event: str) -> bool:
    e = (event or "").lower()
    return any(w in e for w in _SLEEP_START_WORDS)


def _is_end(event: str) -> bool:
    e = (event or "").lower()
    return any(w in e for w in _SLEEP_END_WORDS)


async def _load_sleep_entries(sheets_client: Any, days: int) -> list[dict]:
    """Pull last *days* days of sleep rows from Дневник."""
    rows = await sheets_client.get_baby_diary(days=days)
    parsed = []
    for r in rows:
        d = r.data
        if _kind_clean(d.get("kind", "")) not in ("сон", "sleep"):
            continue
        dt = _parse_entry_dt(d)
        if dt is None:
            continue
        ev = (d.get("event") or "").strip()
        kind_evt = "start" if _is_start(ev) else "end" if _is_end(ev) else "ambiguous"
        parsed.append({"dt": dt, "event": ev, "kind": kind_evt})
    parsed.sort(key=lambda x: x["dt"])
    return parsed


def _pair_episodes(entries: list[dict]) -> list[dict]:
    """Walk start/end pairs into sleep episodes (start, end, duration_min,
    is_night). Ambiguous and orphan starts are ignored."""
    out = []
    open_start = None
    for e in entries:
        if e["kind"] == "start":
            open_start = e["dt"]
        elif e["kind"] == "end" and open_start:
            dur = (e["dt"] - open_start).total_seconds() / 60.0
            if 5 <= dur <= 16 * 60:  # sanity
                # Night = the episode crosses 22:00-06:00 boundary OR has
                # both ends within night hours.
                hour_start = open_start.hour
                hour_end = e["dt"].hour
                is_night = (
                    (hour_start >= 19 or hour_start < 6)
                    or (hour_end >= 6 and hour_start >= 19)
                )
                out.append({
                    "start": open_start, "end": e["dt"],
                    "duration_min": int(dur), "is_night": is_night,
                })
            open_start = None
    return out


def _age_months(birth_date, now_dt) -> float:
    age_days = (now_dt.date() - birth_date).days
    return age_days / 30.4375


async def weekly_analysis(sheets_client: Any, days: int = 14, memory: Any = None) -> dict:
    """Aggregate sleep metrics over the window + age-norm comparison +
    LLM-ready summary string. The actual textual recommendation is built
    by the agent prompt — this helper provides the *facts*."""
    from src.utils.family import CHILD
    from src.utils.time import now_kyiv

    entries = await _load_sleep_entries(sheets_client, days)
    episodes = _pair_episodes(entries)

    now = now_kyiv()
    birth = CHILD.get("birth_date")
    age_m = _age_months(birth, now) if birth else 6.0
    window_min = expected_wake_window_min(age_m)
    naps_str = expected_daytime_naps(age_m)
    total_low, total_high = expected_total_sleep_hours(age_m)

    # Bucket episodes per night
    per_day: dict[str, dict] = {}
    for ep in episodes:
        # Привязка к «ночи»: эпизод с началом после 18:00 = ночь дня X,
        # с концом до 18:00 в день X+1 = всё ещё ночь предыдущего дня.
        anchor = ep["start"]
        if anchor.hour < 12 and not ep["is_night"]:
            day_key = (anchor.date()).isoformat()
        elif ep["is_night"]:
            day_key = (anchor.date() if anchor.hour >= 12
                       else (anchor.date() - timedelta(days=1))).isoformat()
        else:
            day_key = anchor.date().isoformat()
        b = per_day.setdefault(day_key, {
            "naps_min": 0, "night_min": 0, "naps_count": 0,
            "night_wakes": 0, "first_nap_start": None, "last_nap_end": None,
            "night_start": None, "night_end": None,
        })
        if ep["is_night"]:
            b["night_min"] += ep["duration_min"]
            if b["night_start"] is None or ep["start"] < b["night_start"]:
                b["night_start"] = ep["start"]
            if b["night_end"] is None or ep["end"] > b["night_end"]:
                b["night_end"] = ep["end"]
            # If multiple night episodes for same anchor → that's a split
            # night (waking up in the middle).
            if b["night_min"] > ep["duration_min"]:
                b["night_wakes"] += 1
        else:
            b["naps_min"] += ep["duration_min"]
            b["naps_count"] += 1
            if b["first_nap_start"] is None or ep["start"] < b["first_nap_start"]:
                b["first_nap_start"] = ep["start"]
            if b["last_nap_end"] is None or ep["end"] > b["last_nap_end"]:
                b["last_nap_end"] = ep["end"]

    days_observed = len(per_day)
    if days_observed == 0:
        return {
            "age_months": round(age_m, 1),
            "norm": {
                "wake_window_min": window_min,
                "daytime_naps": naps_str,
                "total_sleep_h": [total_low, total_high],
            },
            "observed": {},
            "issues": ["Записей о сне в Дневнике пока нет за этот период."],
            "summary_for_agent": (
                "Нет данных. Скажи юзеру что нужно начать заносить записи о "
                "сне Матвея в Дневник (засыпание и пробуждение), без них анализ "
                "невозможен. Объясни в 1-2 строки как заносить."
            ),
        }

    avg_naps_min = sum(b["naps_min"] for b in per_day.values()) / days_observed
    avg_night_min = sum(b["night_min"] for b in per_day.values()) / days_observed
    avg_total_min = avg_naps_min + avg_night_min
    avg_naps_count = sum(b["naps_count"] for b in per_day.values()) / days_observed

    # Bedtime — среднее время начала ночи
    bedtimes = [b["night_start"].time() for b in per_day.values() if b["night_start"]]
    wakes = [b["night_end"].time() for b in per_day.values() if b["night_end"]]
    last_nap_ends = [b["last_nap_end"].time() for b in per_day.values()
                    if b["last_nap_end"]]
    split_nights = sum(1 for b in per_day.values() if b["night_wakes"] > 0)

    def _avg_time(times):
        if not times:
            return None
        mins = [t.hour * 60 + t.minute for t in times]
        avg = int(sum(mins) / len(mins))
        return f"{avg // 60:02d}:{avg % 60:02d}"

    avg_bedtime = _avg_time(bedtimes)
    avg_wake = _avg_time(wakes)
    avg_last_nap = _avg_time(last_nap_ends)

    issues: list[str] = []

    # Heuristics — flag obvious mismatches
    if avg_bedtime and avg_bedtime < "18:30":
        issues.append(
            f"Bedtime в среднем {avg_bedtime} — слишком рано для "
            f"{age_m:.1f} мес. Норма 19:00-20:30."
        )
    if avg_wake and avg_wake < "06:00":
        issues.append(
            f"Подъём в среднем {avg_wake} — слишком рано. Часто это "
            "следствие слишком раннего bedtime + длинного дневного сна."
        )
    if split_nights >= days_observed / 2:
        issues.append(
            f"{split_nights}/{days_observed} ночей с разрывом (split nights) — "
            "классика циркадного сбоя."
        )
    if avg_last_nap and avg_last_nap > "17:00":
        issues.append(
            f"Последний дневной сон заканчивается в среднем {avg_last_nap} — "
            "поздно. До bedtime должно быть ≥3ч бодрствования."
        )
    if avg_total_min / 60 < total_low - 1:
        issues.append(
            f"Общий сон {avg_total_min / 60:.1f}ч — ниже нормы ({total_low}-"
            f"{total_high}ч)."
        )
    if avg_total_min / 60 > total_high + 1:
        issues.append(
            f"Общий сон {avg_total_min / 60:.1f}ч — выше нормы ({total_low}-"
            f"{total_high}ч)."
        )

    observed = {
        "days_observed": days_observed,
        "avg_naps_min_per_day": round(avg_naps_min, 0),
        "avg_night_min": round(avg_night_min, 0),
        "avg_total_h": round(avg_total_min / 60.0, 1),
        "avg_naps_count": round(avg_naps_count, 1),
        "avg_bedtime": avg_bedtime,
        "avg_morning_wake": avg_wake,
        "avg_last_nap_end": avg_last_nap,
        "split_nights": split_nights,
    }

    # Personalised baseline (его собственный wake-window)
    base = await personal_baseline(sheets_client, days=days)
    his_window = base.get("avg_wake_window_min")
    his_nap = base.get("avg_nap_duration_min")
    his_bedtime = base.get("avg_bedtime_hhmm")
    his_morning = base.get("avg_morning_wake_hhmm")
    base_conf = base.get("confidence", "none")

    personal_line = ""
    if base_conf in ("high", "medium") and his_window:
        personal_line = (
            f"\nЛИЧНЫЙ baseline Матвея (n={base['sample_n']}, "
            f"уверенность {base_conf}):\n"
            f"- его окно бодрствования: {_fmt_hm(his_window)} "
            f"(норма по возрасту {_fmt_hm(window_min)})\n"
        )
        if his_nap:
            personal_line += f"- его дневной сон: ~{_fmt_hm(his_nap)}\n"
        if his_bedtime:
            personal_line += f"- обычный bedtime: {his_bedtime}\n"
        if his_morning:
            personal_line += f"- обычный подъём: {his_morning}\n"

    # Полный timeline за период — даём LLM сырую картинку, чтоб она
    # реально анализировала, а не пересказывала средние.
    timeline_lines = []
    sleep_entries = await _load_sleep_entries(sheets_client, days=days)
    sleep_episodes = _pair_episodes(sleep_entries)
    for ep in sleep_episodes[-30:]:
        tag = "🌙 ночь" if ep["is_night"] else "☀️ день"
        timeline_lines.append(
            f"  {ep['start'].strftime('%d.%m %H:%M')} → "
            f"{ep['end'].strftime('%H:%M')}  ({_fmt_hm(ep['duration_min'])}, {tag})"
        )
    timeline_block = (
        "\n".join(timeline_lines) if timeline_lines else "  (записей нет)"
    )

    # Прошлый трекинг: чему советы сбылись, чему нет.
    advice_block = ""
    if memory is not None:
        try:
            from src.integrations.advice_tracker import recent_advice_summary
            adv = await recent_advice_summary(memory, "nanny", days=4)
            if adv:
                advice_block = f"\nИСТОРИЯ СОВЕТОВ:\n{adv}\n"
        except Exception:
            log.exception("weekly_analysis_advice_block_failed")

    summary_for_agent = (
        f"Матвею {age_m:.1f} мес. Возрастные ориентиры (только как «норма/нет»):\n"
        f"- окно бодрствования {_fmt_hm(window_min)}\n"
        f"- {naps_str} дневных сна\n"
        f"- общий сон {total_low}-{total_high}ч/сут\n"
        f"{personal_line}\n"
        f"СРЕДНИЕ за {days_observed} дней (его реальные):\n"
        f"- общий сон {observed['avg_total_h']}ч "
        f"(ночь {round(avg_night_min/60,1)}ч, днём "
        f"{round(avg_naps_min/60,1)}ч в {observed['avg_naps_count']} снов)\n"
        f"- bedtime ~{avg_bedtime or '—'}, подъём ~{avg_wake or '—'}\n"
        f"- последний дневной сон заканчивается ~{avg_last_nap or '—'}\n"
        f"- ночей с разрывом: {split_nights}/{days_observed}\n\n"
        f"СЫРОЙ TIMELINE последних эпизодов (для реального анализа):\n"
        f"{timeline_block}\n"
        f"{advice_block}\n"
        "ТВОЯ ЗАДАЧА: проанализируй timeline и средние как опытный sleep "
        "coach. НЕ ВЫДАВАЙ ШАБЛОНЫ. Смотри на конкретные цифры этого "
        "ребёнка. Найди:\n"
        "1) Реально хорошо сложилось — что именно (с временами).\n"
        "2) Реальная проблема — что повторяется (с примерами из timeline).\n"
        "3) КОНКРЕТНЫЙ план на сегодня — bedtime во сколько (HH:MM), "
        "когда последний дневной сон закончить, нужно ли сократить какое-то "
        "окно бодрствования. Не общие «попробуйте раньше» — точные HH:MM "
        "и почему именно так.\n\n"
        "ТОН: тёплый, человечный, опытный. Без догматизма. Если данных "
        "мало или картина противоречивая — честно скажи. Коррекция занимает "
        "1-3 недели, магии не обещай. Длительности — формат Хч YYм, "
        "не «120 мин»."
    )

    return {
        "age_months": round(age_m, 1),
        "norm": {
            "wake_window_min": window_min,
            "daytime_naps": naps_str,
            "total_sleep_h": [total_low, total_high],
        },
        "observed": observed,
        "issues": issues,
        "summary_for_agent": summary_for_agent,
    }


async def personal_baseline(sheets_client: Any, days: int = 30) -> dict:
    """Compute Matvey's OWN sleep pattern from the last N days.

    Returns:
      avg_wake_window_min — среднее окно бодрствования (между концом
        предыдущего сна и началом следующего, для дневных циклов).
      avg_nap_duration_min — средняя длина дневного сна.
      avg_night_duration_min — средняя длина ночного.
      avg_bedtime_hhmm — среднее время начала ночного сна.
      avg_morning_wake_hhmm — среднее время утреннего подъёма.
      confidence — 'high' (≥10 wake-windows, 5+ days), 'medium' (3-9),
        'low' (<3) или 'none' (нет данных).
      sample_n — сколько wake-windows реально посчитано.
    """
    entries = await _load_sleep_entries(sheets_client, days)
    episodes = _pair_episodes(entries)

    # 1) Wake-windows: gap between sleep_end of one episode and
    # sleep_start of the next, but only when the gap is within
    # reasonable bounds (≤6 ч — иначе это переход через ночь).
    wake_windows: list[float] = []
    for prev, nxt in zip(episodes, episodes[1:]):
        gap = (nxt["start"] - prev["end"]).total_seconds() / 60.0
        if 20 <= gap <= 360:
            wake_windows.append(gap)

    naps_min = [e["duration_min"] for e in episodes if not e["is_night"]]
    nights_min = [e["duration_min"] for e in episodes if e["is_night"]]

    bedtimes = [e["start"] for e in episodes if e["is_night"]]
    wakes = [e["end"] for e in episodes if e["is_night"]]

    def _avg_time(dts):
        if not dts:
            return None
        mins = [dt.hour * 60 + dt.minute for dt in dts]
        avg = int(sum(mins) / len(mins))
        return f"{avg // 60:02d}:{avg % 60:02d}"

    def _avg(xs):
        return round(sum(xs) / len(xs)) if xs else None

    n = len(wake_windows)
    if n >= 10:
        conf = "high"
    elif n >= 3:
        conf = "medium"
    elif n >= 1:
        conf = "low"
    else:
        conf = "none"

    return {
        "avg_wake_window_min": _avg(wake_windows),
        "avg_nap_duration_min": _avg(naps_min),
        "avg_night_duration_min": _avg(nights_min),
        "avg_bedtime_hhmm": _avg_time(bedtimes),
        "avg_morning_wake_hhmm": _avg_time(wakes),
        "confidence": conf,
        "sample_n": n,
        "days_window": days,
    }


def _personalised_window_min(baseline: dict, age_months: float) -> tuple[int, str]:
    """Return (window_min, source) — prefers Matvey's own average if
    confidence is medium+, otherwise falls back to age norm."""
    if baseline.get("confidence") in ("high", "medium") and baseline.get("avg_wake_window_min"):
        return int(baseline["avg_wake_window_min"]), f"его собственный за {baseline['days_window']}д (n={baseline['sample_n']})"
    return expected_wake_window_min(age_months), "возрастная норма (мало данных по Матвею)"


def _personalised_nap_target(baseline: dict, age_months: float) -> tuple[int, str]:
    if baseline.get("confidence") in ("high", "medium") and baseline.get("avg_nap_duration_min"):
        return int(baseline["avg_nap_duration_min"]), "его собственный"
    # Bootstrap by age
    if age_months <= 6:
        return 75, "возрастная норма"
    if age_months <= 9:
        return 90, "возрастная норма"
    if age_months <= 15:
        return 75, "возрастная норма"
    return 70, "возрастная норма"


async def next_sleep_advice(sheets_client: Any) -> dict:
    """«Прямо сейчас»: куда мы относительно окна бодрствования / спим
    дольше нормы — пора будить?"""
    from src.integrations.baby_state_compute import compute_state_from_diary
    from src.utils.family import CHILD
    from src.utils.time import now_kyiv

    state = await compute_state_from_diary(sheets_client)
    now = now_kyiv()
    birth = CHILD.get("birth_date")
    age_m = _age_months(birth, now) if birth else 6.0
    baseline = await personal_baseline(sheets_client, days=30)
    window_min, window_src = _personalised_window_min(baseline, age_m)

    sleeping_since_iso = state.get("sleeping_since")
    awake_since_iso = state.get("awake_since")

    if sleeping_since_iso:
        sleeping_since = datetime.fromisoformat(sleeping_since_iso)
        slept_min = (now - sleeping_since).total_seconds() / 60.0
        target_min, target_src = _personalised_nap_target(baseline, age_m)
        last_nap_cutoff = now.replace(hour=17, minute=0, second=0, microsecond=0)
        verdict = "ok"
        text_for_agent = (
            f"Матвей спит уже {_fmt_hm(slept_min)} (с {sleeping_since.strftime('%H:%M')})."
            f" Типичная длина дневного сна — около {target_min} мин ({target_src})."
        )
        if slept_min > target_min + 20:
            verdict = "wake_now"
            text_for_agent += (
                " 🟠 Уже перебрал. Если это дневной сон — стоит будить, чтобы не "
                "украсть ночной."
            )
        elif slept_min > target_min - 10:
            verdict = "wake_soon"
            wake_at = (sleeping_since + timedelta(minutes=target_min)).strftime("%H:%M")
            text_for_agent += f" Целевое пробуждение около {wake_at}."
        else:
            wake_at = (sleeping_since + timedelta(minutes=target_min)).strftime("%H:%M")
            text_for_agent += f" Если ничего не менять — проснётся около {wake_at}."

        # Если сейчас уже после 17:00 и спит — это конфликт с ранним bedtime
        if now > last_nap_cutoff:
            text_for_agent += (
                " ⚠️ Сейчас уже после 17:00 — дневной сон в это время "
                "сильно подсушит ночь. Будить."
            )
            verdict = "wake_now"

        return {
            "state": "sleeping",
            "slept_min": int(slept_min),
            "target_min": target_min,
            "verdict": verdict,
            "summary_for_agent": (
                text_for_agent + "\n\nКоротко скажи Марине: «спит X мин, надо…»."
            ),
        }

    if awake_since_iso:
        awake_since = datetime.fromisoformat(awake_since_iso)
        awake_min = (now - awake_since).total_seconds() / 60.0
        until = window_min - awake_min
        next_sleep_at = (awake_since + timedelta(minutes=window_min)).strftime("%H:%M")

        # Готовим СЫРОЙ контекст: timeline последних 48ч + baseline.
        # Никаких пред-выводов — пусть LLM реально анализирует, как
        # делал бы опытный sleep coach глядя на цифры.
        try:
            entries = await _load_sleep_entries(sheets_client, days=2)
            episodes = _pair_episodes(entries)
        except Exception:
            entries, episodes = [], []
            log.exception("sleep_coach_load_failed")

        timeline_lines = []
        for ep in episodes[-20:]:
            tag = "🌙 ночь" if ep["is_night"] else "☀️ день"
            timeline_lines.append(
                f"  {ep['start'].strftime('%d.%m %H:%M')} → "
                f"{ep['end'].strftime('%H:%M')}  ({_fmt_hm(ep['duration_min'])}, {tag})"
            )
        timeline_str = "\n".join(timeline_lines) if timeline_lines else "  (нет данных)"

        base_lines = []
        if baseline.get("avg_wake_window_min"):
            base_lines.append(
                f"  окно бодрствования (среднее за 30д): "
                f"{_fmt_hm(baseline['avg_wake_window_min'])} (n={baseline['sample_n']})"
            )
        if baseline.get("avg_nap_duration_min"):
            base_lines.append(
                f"  средний дневной сон: {_fmt_hm(baseline['avg_nap_duration_min'])}"
            )
        if baseline.get("avg_night_duration_min"):
            base_lines.append(
                f"  средний ночной блок: {_fmt_hm(baseline['avg_night_duration_min'])}"
            )
        if baseline.get("avg_bedtime_hhmm"):
            base_lines.append(f"  обычный bedtime: {baseline['avg_bedtime_hhmm']}")
        if baseline.get("avg_morning_wake_hhmm"):
            base_lines.append(f"  обычный подъём: {baseline['avg_morning_wake_hhmm']}")
        base_str = "\n".join(base_lines) if base_lines else "  (мало данных для baseline)"

        from src.utils.family import CHILD
        total_naps_norm = expected_daytime_naps(age_m)
        sleep_low, sleep_high = expected_total_sleep_hours(age_m)
        norm_str = (
            f"  возрастная норма: окно ~{_fmt_hm(window_min)}, "
            f"{total_naps_norm} дневных сна, общий сон {sleep_low}-{sleep_high}ч/сут"
        )

        summary_for_agent = (
            f"СЕЙЧАС: {now.strftime('%d.%m %H:%M')}. Матвею {age_m:.1f} мес. "
            f"Только что проснулся в {awake_since.strftime('%H:%M')}.\n\n"
            f"TIMELINE последних 48ч (start → end, длительность):\n"
            f"{timeline_str}\n\n"
            f"BASELINE Матвея:\n{base_str}\n\n"
            f"AGE-НОРМА:\n{norm_str}\n\n"
            "ТВОЯ ЗАДАЧА: проанализируй timeline как опытный sleep coach.\n"
            "1) ЧТО ИМЕННО получилось (длительность последнего сна, как он "
            "соотносится с целью, какая была ночь, сколько уже накопилось "
            "дневного сна).\n"
            "2) НАБЛЮДЕНИЕ из истории (что повторяется/изменилось).\n"
            "3) КОНКРЕТНЫЙ совет на ближайший шаг: время следующего "
            "укладывания (HH:MM), длительность (если важно — короткий "
            "20-30 мин или полноценный), что учесть до этого момента.\n\n"
            "ВАЖНО: не подгоняй выводы под шаблон. Смотри на ЦИФРЫ. Если "
            "сон короткий — назови это шортнапом. Если длинный — учти как "
            "это сдвинет вечер. Если необычная картина — назови её. "
            "Используй формат HH:MM для всех времён и Хч YYм для длительностей."
        )

        return {
            "state": "awake",
            "awake_min": int(awake_min),
            "window_min": window_min,
            "next_sleep_at": next_sleep_at,
            "verdict": "ok" if until > 0 else "sleep_now",
            "summary_for_agent": summary_for_agent,
        }

    return {
        "state": "unknown",
        "summary_for_agent": (
            "В Дневнике за последние 36 часов нет записей сна. Без них не могу "
            "понять состояние. Скажи Марине внести «уснул в HH:MM» / «проснулся в HH:MM»."
        ),
    }
