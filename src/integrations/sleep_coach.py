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


async def weekly_analysis(sheets_client: Any, days: int = 14) -> dict:
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
            f"- его окно бодрствования: {his_window} мин "
            f"(норма по возрасту {window_min})\n"
        )
        if his_nap:
            personal_line += f"- его дневной сон: ~{his_nap} мин\n"
        if his_bedtime:
            personal_line += f"- обычный bedtime: {his_bedtime}\n"
        if his_morning:
            personal_line += f"- обычный подъём: {his_morning}\n"

    summary_for_agent = (
        f"Матвею {age_m:.1f} мес. По возрастной норме (Weissbluth):\n"
        f"- окно бодрствования {window_min} мин\n"
        f"- {naps_str} дневных сна\n"
        f"- общий сон {total_low}-{total_high}ч/сут\n"
        f"{personal_line}\n"
        f"ФАКТИЧЕСКИ за {days_observed} дней:\n"
        f"- общий сон {observed['avg_total_h']}ч (ночь {round(avg_night_min/60,1)}ч, "
        f"днём {round(avg_naps_min/60,1)}ч в {observed['avg_naps_count']} снов)\n"
        f"- bedtime ~{avg_bedtime or '—'}, подъём ~{avg_wake or '—'}\n"
        f"- последний дневной сон заканчивается ~{avg_last_nap or '—'}\n"
        f"- ночей с разрывом: {split_nights}/{days_observed}\n\n"
        f"ПРОБЛЕМЫ:\n" + ("\n".join(f"- {i}" for i in issues) if issues else "- не вижу явных")
        + "\n\nДай 2-3 КОНКРЕТНЫХ совета на сегодня (bedtime во сколько, последний "
        "дневной сон завершить во сколько, что менять в первую очередь). "
        "ВАЖНО: опирайся на ЛИЧНЫЙ baseline Матвея (его реальные средние), "
        "а не на возрастную норму. Возрастная норма — только ориентир «нормально/нет». "
        "Тёплый тон, без догматизма. Помни: коррекция занимает 1-3 недели, "
        "магии не будет. Если данных мало (confidence='low'/'none') — "
        "честно скажи Марине, что выводы предварительные, нужно ещё неделя "
        "записей для надёжного личного baseline."
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

        # «Только что проснулся» — посчитать длительность ПРЕДЫДУЩЕГО
        # сна и сравнить с целью. Это критично чтобы Няня не писала
        # «отлично выспался» когда фактически шортнап.
        last_sleep_verdict: dict = {}
        try:
            entries = await _load_sleep_entries(sheets_client, days=2)
            episodes = _pair_episodes(entries)
            # Самый свежий эпизод чей end ≈ awake_since (с допуском 2 мин)
            for ep in reversed(episodes):
                if abs((ep["end"] - awake_since).total_seconds()) <= 120:
                    dur = ep["duration_min"]
                    nap_target, target_src = _personalised_nap_target(baseline, age_m)
                    if ep["is_night"]:
                        # Ночной — нужен иной таргет; не цепляемся.
                        last_sleep_verdict = {
                            "label": "night",
                            "duration_min": dur,
                            "summary": f"ночной сон {_fmt_hm(dur)}",
                        }
                    else:
                        if dur < nap_target * 0.7:
                            label = "short"
                            tone = (
                                f"⚠️ КОРОТКИЙ дневной сон: {int(dur)} мин при "
                                f"типичной длине ~{nap_target} мин ({target_src}). "
                                "Это шортнап — Матвей мог недоспать. Окно "
                                "бодрствования к следующему сну СОКРАТИ "
                                "(~70-80% от обычного), иначе перегул "
                                "и сложное укладывание."
                            )
                        elif dur > nap_target * 1.3:
                            label = "long"
                            tone = (
                                f"Длинный дневной сон: {int(dur)} мин при "
                                f"типичной длине ~{nap_target} мин ({target_src}). "
                                "Если будет ещё сон сегодня — учти что вечерний "
                                "может быть труднее. Bedtime возможно сдвинется."
                            )
                        else:
                            label = "ok"
                            tone = (
                                f"Длительность сна в норме: {int(dur)} мин "
                                f"(целевая ~{nap_target} мин)."
                            )
                        last_sleep_verdict = {
                            "label": label,
                            "duration_min": int(dur),
                            "target_min": int(nap_target),
                            "summary": tone,
                        }
                    break
        except Exception:
            log.exception("sleep_coach_last_episode_failed")

        if until > 30:
            text_for_agent = (
                f"Бодрствует {_fmt_hm(awake_min)} (с {awake_since.strftime('%H:%M')})."
                f" До типичного окна сна (~{window_min} мин — {window_src}) "
                f"осталось ~{int(until)} мин — укладывать около {next_sleep_at}."
            )
            verdict = "ok"
        elif until > 0:
            text_for_agent = (
                f"Бодрствует {_fmt_hm(awake_min)}. До окна сна осталось ~{int(until)} мин. "
                f"Готовь к укладыванию (приглуши свет, тише). Цель: {next_sleep_at}."
            )
            verdict = "prep"
        else:
            over = -until
            text_for_agent = (
                f"🟠 Перегул: бодрствует {_fmt_hm(awake_min)}, окно ~{window_min} мин. "
                f"Перебор {int(over)} мин. Уложи СЕЙЧАС — дольше будет сложнее."
            )
            verdict = "sleep_now"

        prev_sleep_block = ""
        if last_sleep_verdict.get("summary"):
            prev_sleep_block = (
                f"\n\nПРЕДЫДУЩИЙ СОН (только что закончился):\n"
                f"{last_sleep_verdict['summary']}\n"
                "ВАЖНО: тон твоего ответа должен соответствовать этой "
                "оценке. Если КОРОТКИЙ — НЕ пиши «отлично выспался», "
                "это введёт Марину в заблуждение. Признай факт, "
                "предложи корректировку (сократить wake window)."
            )

        return {
            "state": "awake",
            "awake_min": int(awake_min),
            "window_min": window_min,
            "next_sleep_at": next_sleep_at,
            "verdict": verdict,
            "last_sleep": last_sleep_verdict,
            "summary_for_agent": (
                text_for_agent + prev_sleep_block +
                "\n\nКоротко скажи Марине одной-двумя фразами."
            ),
        }

    return {
        "state": "unknown",
        "summary_for_agent": (
            "В Дневнике за последние 36 часов нет записей сна. Без них не могу "
            "понять состояние. Скажи Марине внести «уснул в HH:MM» / «проснулся в HH:MM»."
        ),
    }
