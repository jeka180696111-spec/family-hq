"""Parse photo captions for dates / age markers.

Supports:
  '02.12.2025' / '02.12.25'      — DD.MM.YYYY
  '2 декабря 2025' / '2 декабря' — Russian month name
  '2 грудня 2025'                — Ukrainian month name
  'роддом' / 'выписка'           — special anchors
  '2 мес' / '6 месяцев' / '3 нед'/ '10 дн' — age relative to baby DOB

Returns datetime or None.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from src.utils.time import KYIV_TZ, now_kyiv

BABY_DOB = datetime(2025, 12, 2, 10, 0, tzinfo=KYIV_TZ)

_RU_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "мая": 5, "мае": 5,
    "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
_UA_MONTHS = {
    "січн": 1, "лют": 2, "берез": 3, "квіт": 4, "трав": 5,
    "черв": 6, "лип": 7, "серп": 8, "верес": 9, "жовт": 10, "листопад": 11, "груд": 12,
}
_ANCHOR_WORDS = {
    "роддом": BABY_DOB,
    "родом": BABY_DOB,  # typo tolerance
    "роддома": BABY_DOB,
    "выписка": BABY_DOB + timedelta(days=4),
    "выписк": BABY_DOB + timedelta(days=4),
}


def parse_caption_date(caption: str, fallback: Optional[datetime] = None) -> Optional[datetime]:
    if not caption:
        return None
    text = caption.lower().strip()

    # 1) Anchor word (роддом / выписка)
    for word, dt in _ANCHOR_WORDS.items():
        if word in text:
            return dt

    # 2) Explicit DD.MM.YYYY or DD.MM.YY or DD/MM/YYYY
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return datetime(y, mo, d, 12, 0, tzinfo=KYIV_TZ)
        except ValueError:
            pass

    # 3) DD.MM (no year) — assume same year as fallback / today
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})\b", text)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        year = (fallback or now_kyiv()).year
        try:
            return datetime(year, mo, d, 12, 0, tzinfo=KYIV_TZ)
        except ValueError:
            pass

    # 4) Russian/Ukrainian month name
    for table in (_RU_MONTHS, _UA_MONTHS):
        for stem, mo in table.items():
            if stem in text:
                # find day before the month
                dm = re.search(rf"(\d{{1,2}})\s+{stem}", text)
                day = int(dm.group(1)) if dm else 15
                # year — search 4-digit nearby, else current
                ym = re.search(r"\b(20\d{2})\b", text)
                year = int(ym.group(1)) if ym else (fallback or now_kyiv()).year
                try:
                    return datetime(year, mo, day, 12, 0, tzinfo=KYIV_TZ)
                except ValueError:
                    pass

    # 5) Relative to baby DOB: '2 мес', '6 месяцев', '3 нед', '10 дн'
    m = re.search(r"(\d+)\s*(мес|месяц|month|нед|тиж|week|дн|day|год|г\b)", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "мес" in unit or "месяц" in unit or "month" in unit:
            # +n months from DOB (rough)
            year = BABY_DOB.year + (BABY_DOB.month - 1 + n) // 12
            month = (BABY_DOB.month - 1 + n) % 12 + 1
            day = min(BABY_DOB.day, 28)
            return datetime(year, month, day, 12, 0, tzinfo=KYIV_TZ)
        if "нед" in unit or "тиж" in unit or "week" in unit:
            return BABY_DOB + timedelta(weeks=n)
        if "дн" in unit or "day" in unit:
            return BABY_DOB + timedelta(days=n)
        if "год" in unit or unit == "г":
            return BABY_DOB.replace(year=BABY_DOB.year + n)

    return None
