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
