"""Family profile — single source of truth for who's who.

Loaded into every agent's system prompt so they know names, ages, medical
context, schedules, location. Edit this file to update.
"""
from __future__ import annotations

from datetime import date

from src.utils.baby import MATVEY_BIRTH_DATE, matvey_age_short

# ─────────────────────────────────────────────────────────────────────
# Family members
# ─────────────────────────────────────────────────────────────────────

CHILD = {
    "full_name": "Киосе Матвей Евгенийович",
    "short_name": "Матвей",
    "birth_date": MATVEY_BIRTH_DATE,      # 02.12.2025
    "delivery": "кесарево, в срок",
    "feeding": "ГВ (грудное вскармливание)",
    "weight_g": 9000,
    "height_cm": 72,
    "allergies": [],
    "introduced_foods": ["кабачок", "цветная капуста", "банан"],
    "vaccines_done": [
        "БЦЖ",
        "Инфанрикс гекса (1)",
        "Инфанрикс гекса (2) — 09.02.2026",
        "Ротарикс (1)",
        "Ротарикс (2) — 01.06.2026",
    ],
    "vaccines_upcoming": [
        ("Инфанрикс гекса (3)", date(2026, 6, 10)),
    ],
}

FATHER = {
    "full_name": "Киосе Евгений Сергеевич",
    "short_name": "Евгений",
    "role": "Папочка",
    "birth_date": date(1996, 6, 18),
    "weight_kg": 85,
    "blood_type": "II Rh+ (A+)",
    "allergies": [],
    "medical_history": [
        "Недавно переболел туберкулёзом — медотвод и наблюдение фтизиатра актуальны",
        "Уволен из армии в ноябре 2025",
    ],
    "schedule": "пн-пт 08:30-17:00 (офис, плюс дорога) — недоступен 07:00-18:30",
}

MOTHER = {
    "full_name": "Клименко Марина Федоровна",
    "short_name": "Марина",
    "role": "Мамочка",
    "birth_date": date(1997, 9, 12),
    "weight_kg": 55,
    "blood_type": "не уверена",
    "allergies": [],
    "medical_history": [],
    "lactating": True,   # Важно для расчёта доз и совместимости лекарств
    "schedule": "в декрете, всегда дома",
}

HELPERS = [
    {"role": "Бабушка С.", "full_name": "Бабушка Светлана (мама Марины)"},
    {"role": "Бабушка А.", "full_name": "Бабушка Алёна (мама Евгения)"},
]

LOCATION = {
    "city": "Одесса",
    "district": "Приморский район",
    "country": "Украина",
}

PEDIATRICS = {
    "doctor": "Панкова Татьяна Александровна",
    "clinic": "Городская детская поликлиника №5",
    "address": "ул. Евгения Танцюры, 80, Одесса",
}

BABY_SCHEDULE_NOTE = "Режим сна/еды у Матвея пока нерегулярный — спрашивай у Няни перед планированием."

FINANCE = {
    "currency": "UAH",
    "monthly_baby_budget": 10000,  # грн/мес ориентир
}


def _age(birth: date) -> str:
    today = date.today()
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return f"{years} лет"


# ─── Runtime overrides (synced from family_overrides table) ────────────────
# Keys with dotted notation: 'matvey.weight_g', 'current_location.city',
# 'current_location.until_date', etc.

_OVERRIDES: dict[str, str] = {}


def apply_overrides(overrides: dict[str, str]) -> None:
    """Replace the in-memory override map. Called by main on startup + after edits."""
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def get_override(key: str, default=None):
    return _OVERRIDES.get(key, default)


def _current_location() -> dict:
    city = get_override("current_location.city")
    if not city:
        return LOCATION
    return {
        "city": city,
        "district": get_override("current_location.district", ""),
        "country": get_override("current_location.country", LOCATION["country"]),
        "until": get_override("current_location.until_date", ""),
    }


def _override_int(key: str, default: int) -> int:
    raw = get_override(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def family_context_block() -> str:
    """Formatted summary inserted into agent system prompts."""
    matvey_age = matvey_age_short()
    father_age = _age(FATHER["birth_date"])
    mother_age = _age(MOTHER["birth_date"])
    loc = _current_location()
    weight_g = _override_int("matvey.weight_g", CHILD["weight_g"])
    height_cm = _override_int("matvey.height_cm", CHILD["height_cm"])

    loc_line = f"📍 {loc['city']}, {loc['district']} ({loc['country']})".rstrip(", )")
    if loc.get("until"):
        loc_line += f"  ⚠️ временно до {loc['until']} (дома: {LOCATION['city']})"

    lines = [
        "═══ СЕМЬЯ ═══",
        loc_line,
        "",
        f"👶 Малыш: {CHILD['full_name']}",
        f"   род. {CHILD['birth_date'].strftime('%d.%m.%Y')}, сейчас {matvey_age}",
        f"   {CHILD['delivery']}; {CHILD['feeding']}; {weight_g}г / {height_cm}см",
        f"   Пробовал: {', '.join(CHILD['introduced_foods']) or 'ничего'}",
        f"   Аллергий: {', '.join(CHILD['allergies']) or 'нет'}",
        f"   Прививки: {'; '.join(CHILD['vaccines_done'])}",
    ]
    if CHILD["vaccines_upcoming"]:
        upcoming = ", ".join(f"{name} {dt.strftime('%d.%m.%Y')}" for name, dt in CHILD["vaccines_upcoming"])
        lines.append(f"   Следующая: {upcoming}")

    lines += [
        "",
        f"👨 Папа: {FATHER['short_name']} ({FATHER['full_name']}), {father_age}",
        f"   {FATHER['weight_kg']} кг, {FATHER['blood_type']}",
        f"   Анамнез: {'; '.join(FATHER['medical_history']) or 'без особенностей'}",
        f"   Расписание: {FATHER['schedule']}",
        "",
        f"👩 Мама: {MOTHER['short_name']} ({MOTHER['full_name']}), {mother_age}",
        f"   {MOTHER['weight_kg']} кг, группа крови {MOTHER['blood_type']}",
        f"   {'Кормит грудью — учитывай совместимость лекарств' if MOTHER.get('lactating') else 'Не кормит'}",
        f"   Расписание: {MOTHER['schedule']}",
        "",
        "👵 Помощники:",
    ]
    for h in HELPERS:
        lines.append(f"   — {h['role']}: {h['full_name']}")

    lines += [
        "",
        "🏥 Педиатрия:",
        f"   {PEDIATRICS['doctor']}",
        f"   {PEDIATRICS['clinic']}, {PEDIATRICS['address']}",
        "",
        f"💰 Финансы: валюта {FINANCE['currency']}, ориентир по малышу {FINANCE['monthly_baby_budget']} {FINANCE['currency']}/мес",
        "═══",
    ]
    return "\n".join(lines)
