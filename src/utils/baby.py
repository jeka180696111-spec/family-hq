"""Shared baby data — single source of truth for Matvey's profile."""
from __future__ import annotations

from datetime import date

MATVEY_BIRTH_DATE = date(2025, 12, 2)


def matvey_age_months() -> int:
    today = date.today()
    months = (today.year - MATVEY_BIRTH_DATE.year) * 12 + (today.month - MATVEY_BIRTH_DATE.month)
    if today.day < MATVEY_BIRTH_DATE.day:
        months -= 1
    return max(months, 0)


def _months_word(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return "месяцев"
    last = n % 10
    if last == 1:
        return "месяц"
    if 2 <= last <= 4:
        return "месяца"
    return "месяцев"


def _years_word(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return "лет"
    last = n % 10
    if last == 1:
        return "год"
    if 2 <= last <= 4:
        return "года"
    return "лет"


def matvey_age_human() -> str:
    """Human-readable age in Russian: '6 месяцев', '1 год', '1 год и 2 месяца', '2 года'."""
    m = matvey_age_months()
    if m < 12:
        return f"{m} {_months_word(m)}"
    years = m // 12
    rem = m % 12
    if rem == 0:
        return f"{years} {_years_word(years)}"
    return f"{years} {_years_word(years)} и {rem} {_months_word(rem)}"
