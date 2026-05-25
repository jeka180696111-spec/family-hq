from __future__ import annotations
import re
from datetime import datetime, time
from typing import Final
import zoneinfo


def _kyiv_tz() -> zoneinfo.ZoneInfo:
    """Return the Kyiv ZoneInfo, trying both the legacy and current IANA key."""
    for key in ("Europe/Kyiv", "Europe/Kiev"):
        try:
            return zoneinfo.ZoneInfo(key)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            continue
    raise RuntimeError(
        "Could not load Europe/Kyiv timezone. "
        "Install the 'tzdata' package: pip install tzdata"
    )


KYIV_TZ: Final = _kyiv_tz()

# Ukrainian month abbreviations (nominative short form)
_UA_MONTHS: Final[dict[int, str]] = {
    1: "Січ",
    2: "Лют",
    3: "Бер",
    4: "Кві",
    5: "Тра",
    6: "Чер",
    7: "Лип",
    8: "Сер",
    9: "Вер",
    10: "Жов",
    11: "Лис",
    12: "Гру",
}

# Simple pattern table for parse_message_time
_RE_HH_MM = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_RE_HOUR_OF_DAY = re.compile(
    r"\b(?:в\s+)?(\d{1,2})\s+(?:год(?:ин[іу]?)?|hour)",
    re.IGNORECASE | re.UNICODE,
)

# "в час дня" → 13:00,  "в два дня" → 14:00, etc.
_UA_WORD_HOURS: Final[dict[str, int]] = {
    "один": 1,
    "одну": 1,
    "два": 2,
    "дві": 2,
    "три": 3,
    "чотири": 4,
    "п'ять": 5,
    "шість": 6,
    "сім": 7,
    "вісім": 8,
    "дев'ять": 9,
    "десять": 10,
    "одинадцять": 11,
    "дванадцять": 12,
    "час": 1,  # "в час дня" → 13:00 handled below
}

_RE_WORD_HOUR = re.compile(
    r"\b(?:в\s+)?("
    + "|".join(re.escape(w) for w in _UA_WORD_HOURS)
    + r")\s*(дня|вечора|ранку|ночі)?\b",
    re.IGNORECASE | re.UNICODE,
)

_PERIOD_OFFSET: Final[dict[str, int]] = {
    "дня": 12,    # afternoon → add 12 if hour < 12
    "вечора": 12,
    "ночі": 0,
    "ранку": 0,
}


def now_kyiv() -> datetime:
    """Current datetime in Kyiv timezone."""
    return datetime.now(KYIV_TZ)


def parse_time_str(time_str: str) -> time:
    """Parse 'HH:MM' string to time object."""
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time string: {time_str!r}")
    hour, minute = int(parts[0]), int(parts[1])
    return time(hour, minute)


def format_dt(dt: datetime) -> str:
    """Format datetime for display in Ukrainian style: '15 Лис, 14:30'."""
    month_abbr = _UA_MONTHS.get(dt.month, str(dt.month))
    return f"{dt.day} {month_abbr}, {dt.hour:02d}:{dt.minute:02d}"


def iso_now() -> str:
    """Current time as ISO string for DB storage."""
    return now_kyiv().isoformat()


def parse_message_time(text: str, reference: datetime | None = None) -> datetime | None:
    """Try to parse time mentions from user messages.

    Handled patterns:
    - '14:30'
    - 'в 14:30'
    - 'в час дня' / 'в два ночі'
    - 'тільки що' / 'только что'

    Returns None if no recognisable time expression is found.
    """
    ref = reference if reference is not None else now_kyiv()

    # "тільки що" / "только что" → now
    if re.search(r"тільки\s+що|только\s+что", text, re.IGNORECASE | re.UNICODE):
        return ref

    # HH:MM (most specific — try first)
    match = _RE_HH_MM.search(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        return ref.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Numeric hour with optional period  e.g. "в 14 годині", "о 9 год"
    match = _RE_HOUR_OF_DAY.search(text)
    if match:
        hour = int(match.group(1))
        return ref.replace(hour=hour % 24, minute=0, second=0, microsecond=0)

    # Word-based Ukrainian hour
    match = _RE_WORD_HOUR.search(text)
    if match:
        word = match.group(1).lower()
        period = (match.group(2) or "").lower()
        hour = _UA_WORD_HOURS.get(word)
        if hour is not None:
            offset = _PERIOD_OFFSET.get(period, 0)
            if offset and hour < 12:
                hour += offset
            elif word == "час" and period in ("дня", "вечора"):
                hour = 13  # "в час дня" conventionally means 13:00 in Ukrainian
            return ref.replace(hour=hour % 24, minute=0, second=0, microsecond=0)

    return None
