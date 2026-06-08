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

# ─── Экстренные службы Одессы ───────────────────────────────────────────
EMERGENCY_CONTACTS = [
    {"name": "Полиция (общий)", "phone": "102"},
    {"name": "Скорая помощь", "phone": "103"},
    {"name": "Пожарная служба / ДСНС", "phone": "101"},
    {"name": "Газовая служба", "phone": "104"},
    {"name": "Единая служба спасения", "phone": "112"},
    {"name": "Детская скорая помощь Одесса", "phone": "+380 48 700-04-04"},
    {"name": "Детская поликлиника №5", "phone": "+380 48 760-67-67"},
    {"name": "Одесский областной фтизиопульмонологический центр", "phone": "+380 48 715-15-00"},
    {"name": "Облэнерго Одесса (отключения)", "phone": "0 800 502 102"},
    {"name": "Инфоцентр ДСНС Одесской области", "phone": "+380 48 705-21-01"},
]

# ─── План эвакуации ─────────────────────────────────────────────────────
EVACUATION = {
    "primary_shelter": "Подвал дома (укрытие 1 этаж)",
    "backup_shelter": "Метро Чкалова (старая станция, ближайшая защищённая)",
    "route": "Из квартиры → лифт/лестница вниз → подвал. Если опасно — выход во двор → к метро.",
    "go_bag": [
        "Документы (паспорта, свидетельство о рождении Матвея, медкарта)",
        "Деньги (наличные UAH + USD)",
        "Телефоны + павербанки + зарядки",
        "Вода 1-2л + перекус",
        "Аптечка (нурофен детский, эспумизан, бинт, антисептик, термометр)",
        "Малыш: 4-5 памперсов, 2 смены одежды, влажные салфетки, бутылочка, плед",
        "Фонарик + батарейки",
        "Нож/мультитул",
        "Ключи (дом, машина если есть)",
    ],
    "reminder": "Сумка должна быть собрана и стоять у двери. Проверять раз в месяц.",
}

# ─── Чек-лист «выезд с малышом» (не путать с эвакуацией) ────────────────
BABY_TRIP_CHECKLIST = [
    "Памперсы (минимум 3 + 1 запас)",
    "Влажные салфетки",
    "Запасная одежда (1 комплект)",
    "Слюнявчик/боди",
    "Бутылочка + вода (если на смеси — порция смеси)",
    "Пюре в баночке (если по времени попадает кормление)",
    "Ложечка",
    "Плед/пелёнка тонкая",
    "Игрушка-погремушка",
    "Влажные салфетки для рук",
    "Полиэтиленовый пакет (для грязного)",
    "Аптечка-минимум: парацетамол детский, термометр",
    "Свидетельство о рождении (для поликлиники/прививок)",
    "Деньги, карта, ключи",
]

# ─── Календарь развития (ВОЗ + педиатрия) 6-12 мес ──────────────────────
WHO_MILESTONES = {
    6: {
        "motor": ["Уверенно держит голову лёжа на животе", "Перекатывается с живота на спину и обратно", "Сидит с поддержкой"],
        "fine_motor": ["Берёт игрушку из руки в руку", "Тянет всё в рот для изучения"],
        "social": ["Узнаёт родителей", "Улыбается на знакомые лица", "Смеётся в голос"],
        "speech": ["Гулит, агукает", "Реагирует на своё имя"],
        "play": ["Игрушки-погремушки", "Прорезыватели", "Книжки-картонки контрастные"],
        "food": ["Старт прикорма — овощи (кабачок, брокколи, цветная капуста), потом каши безмолочные"],
        "danger_flags": ["НЕ удерживает голову", "НЕ перекатывается совсем", "НЕ реагирует на звуки"],
    },
    7: {
        "motor": ["Сидит без опоры (короткими интервалами)", "Опирается на руки лёжа на животе"],
        "fine_motor": ["Перекладывает игрушку из руки в руку", "Держит две вещи одновременно"],
        "social": ["Стесняется незнакомых", "Понимает интонацию"],
        "speech": ["Слоги: «ба», «ма», «па»", "Подражает звукам"],
        "play": ["Мячик мягкий", "Зеркало небьющееся", "Книжки текстурные"],
        "food": ["Можно: морковь, тыква. Каши гречка/рис безмолочные. Мясо индейки/кролика (10-20г)"],
        "danger_flags": ["НЕ опирается на руки лёжа", "НЕ берёт предметы"],
    },
    8: {
        "motor": ["Сидит уверенно", "Может встать на четвереньки", "Пробует ползти"],
        "fine_motor": ["Захват двумя пальцами (большой+указательный)"],
        "social": ["Боязнь чужих", "Радуется родителям"],
        "speech": ["«Мама», «папа» (без значения)", "Повторяет цепочки слогов"],
        "play": ["Пирамидка с большими кольцами", "Кубики мягкие"],
        "food": ["Можно: фрукты (яблоко, груша печёные), кисломолочка (творог 30г, кефир)"],
        "danger_flags": ["НЕ сидит даже короткими интервалами"],
    },
    9: {
        "motor": ["Ползает", "Подтягивается к опоре"],
        "fine_motor": ["Пинцетный захват (берёт мелкое)"],
        "social": ["Машет «пока-пока»", "Играет в «ладушки»"],
        "speech": ["Понимает «нет»", "Реагирует на простые просьбы"],
        "play": ["Машинки/каталки", "Сортеры простые"],
        "food": ["Можно: рыба (хек, треска) 30г, желток 1/4, хлеб подсушенный"],
        "danger_flags": ["НЕ ползает совсем", "НЕ держит предметы"],
    },
    10: {
        "motor": ["Стоит у опоры", "Делает шаги вдоль мебели"],
        "fine_motor": ["Перекладывает мелкое", "Учится отдавать предмет"],
        "social": ["Понимает простые команды («дай», «на»)"],
        "speech": ["3-5 «слов» (мама, папа, дай, на, нет)"],
        "play": ["Кубики, пирамидки", "Сюжетные игрушки (кукла, машинка)"],
        "food": ["Можно: молочные каши, печенье детское, фрукты сырые мягкие"],
        "danger_flags": ["НЕ встаёт у опоры"],
    },
    11: {
        "motor": ["Стоит сам пару секунд", "Может сделать пару шагов с поддержкой"],
        "fine_motor": ["Использует ложку (плохо, но пробует)"],
        "social": ["Помогает одеваться (поднимает руки)"],
        "speech": ["Понимает 10-15 слов", "Пытается повторять"],
        "play": ["Книжки с короткими историями", "Музыкальные игрушки"],
        "food": ["Стол семьи с осторожностью (без соли/сахара/специй). Мясо кусочками"],
        "danger_flags": ["НЕ стоит даже с опорой"],
    },
    12: {
        "motor": ["Делает первые самостоятельные шаги", "Залазит на низкие предметы"],
        "fine_motor": ["Чёткий пинцетный захват", "Открывает коробки"],
        "social": ["Обнимает", "Кивает «да» / мотает «нет»"],
        "speech": ["5-10 осмысленных слов"],
        "play": ["Мяч (катать), сортеры, простые пазлы 2-3 элемента"],
        "food": ["Почти весь стол семьи (без аллергенов и острого). Коровье молоко после года"],
        "danger_flags": ["Полное отсутствие слов", "Не стоит совсем"],
    },
}


def emergency_block() -> str:
    lines = ["═══ ЭКСТРЕННЫЕ КОНТАКТЫ ═══"]
    for c in EMERGENCY_CONTACTS:
        lines.append(f"  {c['phone']:<20} {c['name']}")
    lines.append("")
    lines.append("═══ ЭВАКУАЦИЯ ═══")
    lines.append(f"  Укрытие: {EVACUATION['primary_shelter']}")
    lines.append(f"  Резерв: {EVACUATION['backup_shelter']}")
    lines.append("  В тревожной сумке: " + ", ".join(EVACUATION["go_bag"][:5]) + ", …")
    lines.append("═══")
    return "\n".join(lines)


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
_WIKI_FACTS: list[dict] = []


def apply_overrides(overrides: dict[str, str]) -> None:
    """Replace the in-memory override map. Called by main on startup + after edits."""
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def apply_wiki_facts(facts: list[dict]) -> None:
    """Replace the in-memory wiki cache. Called on startup + after wiki edits."""
    _WIKI_FACTS.clear()
    _WIKI_FACTS.extend(facts)


def get_wiki_facts() -> list[dict]:
    return list(_WIKI_FACTS)


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
    from src.prompts._team import family_wiki_block
    wiki = family_wiki_block(_WIKI_FACTS)
    if wiki:
        lines.append(wiki)
    return "\n".join(lines)
