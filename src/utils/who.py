"""WHO weight-for-age percentiles (boys) — simplified table for 0-24 months.

Source: WHO Child Growth Standards (boys).
Values are kg at the 3rd / 15th / 50th / 85th / 97th percentile per month.
"""
from __future__ import annotations

# (3rd, 15th, 50th, 85th, 97th) percentile weights in kg by age_months 0..24
_BOY_WEIGHT = {
    0:  (2.5, 2.9, 3.3, 3.9, 4.4),
    1:  (3.4, 3.9, 4.5, 5.1, 5.8),
    2:  (4.4, 4.9, 5.6, 6.3, 7.1),
    3:  (5.1, 5.7, 6.4, 7.2, 8.0),
    4:  (5.6, 6.2, 7.0, 7.8, 8.7),
    5:  (6.1, 6.7, 7.5, 8.4, 9.3),
    6:  (6.4, 7.1, 7.9, 8.8, 9.8),
    7:  (6.7, 7.4, 8.3, 9.2, 10.3),
    8:  (6.9, 7.7, 8.6, 9.6, 10.7),
    9:  (7.1, 7.9, 8.9, 9.9, 11.0),
    10: (7.4, 8.2, 9.2, 10.2, 11.4),
    11: (7.6, 8.4, 9.4, 10.5, 11.7),
    12: (7.7, 8.6, 9.6, 10.8, 12.0),
    15: (8.3, 9.2, 10.3, 11.5, 12.8),
    18: (8.8, 9.8, 10.9, 12.2, 13.7),
    21: (9.2, 10.3, 11.5, 12.9, 14.5),
    24: (9.7, 10.8, 12.2, 13.6, 15.3),
}

# Height (cm) percentiles by age_months 0..24
_BOY_HEIGHT = {
    0:  (46.1, 47.9, 49.9, 51.8, 53.7),
    1:  (50.8, 52.7, 54.7, 56.7, 58.6),
    2:  (54.4, 56.4, 58.4, 60.4, 62.4),
    3:  (57.3, 59.4, 61.4, 63.5, 65.5),
    4:  (59.7, 61.8, 63.9, 66.0, 68.0),
    5:  (61.7, 63.8, 65.9, 68.0, 70.1),
    6:  (63.3, 65.5, 67.6, 69.8, 71.9),
    7:  (64.8, 67.0, 69.2, 71.3, 73.5),
    8:  (66.2, 68.4, 70.6, 72.8, 75.0),
    9:  (67.5, 69.7, 72.0, 74.2, 76.5),
    10: (68.7, 71.0, 73.3, 75.6, 77.9),
    11: (69.9, 72.2, 74.5, 76.9, 79.2),
    12: (71.0, 73.4, 75.7, 78.1, 80.5),
    15: (74.1, 76.6, 79.1, 81.6, 84.2),
    18: (76.9, 79.6, 82.3, 85.0, 87.7),
    21: (79.4, 82.3, 85.1, 88.0, 90.9),
    24: (81.7, 84.8, 87.8, 90.9, 93.9),
}


def _nearest(table: dict[int, tuple], age_months: int) -> tuple:
    keys = sorted(table.keys())
    best = keys[0]
    for k in keys:
        if k <= age_months:
            best = k
    return table[best]


def percentile_bucket(value: float, p3: float, p15: float, p50: float, p85: float, p97: float) -> str:
    """Map a measurement to a human-readable percentile range."""
    if value < p3:
        return "ниже 3-го перцентиля"
    if value < p15:
        return "3-15-й перцентиль (ниже среднего)"
    if value < p50:
        return "15-50-й перцентиль (норма, чуть ниже среднего)"
    if value < p85:
        return "50-85-й перцентиль (норма, чуть выше среднего)"
    if value < p97:
        return "85-97-й перцентиль (выше среднего)"
    return "выше 97-го перцентиля"


def weight_percentile(weight_kg: float, age_months: int, sex: str = "boy") -> dict:
    """Returns percentile bucket + reference values for a weight measurement."""
    table = _BOY_WEIGHT  # only boys for now
    p3, p15, p50, p85, p97 = _nearest(table, age_months)
    return {
        "measurement_kg": weight_kg,
        "age_months": age_months,
        "bucket": percentile_bucket(weight_kg, p3, p15, p50, p85, p97),
        "reference_kg": {"p3": p3, "p15": p15, "p50": p50, "p85": p85, "p97": p97},
        "interpretation": (
            "В норме" if p3 <= weight_kg <= p97 else
            "Вне нормы по ВОЗ — обсуди с педиатром"
        ),
    }


def height_percentile(height_cm: float, age_months: int, sex: str = "boy") -> dict:
    table = _BOY_HEIGHT
    p3, p15, p50, p85, p97 = _nearest(table, age_months)
    return {
        "measurement_cm": height_cm,
        "age_months": age_months,
        "bucket": percentile_bucket(height_cm, p3, p15, p50, p85, p97),
        "reference_cm": {"p3": p3, "p15": p15, "p50": p50, "p85": p85, "p97": p97},
        "interpretation": (
            "В норме" if p3 <= height_cm <= p97 else
            "Вне нормы по ВОЗ — обсуди с педиатром"
        ),
    }
