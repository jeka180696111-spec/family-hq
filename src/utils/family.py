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
    "nicknames": [
        "Женя", "Женечка", "Жека",
        "Муж", "Мужик",
        "Пап", "Папа", "Папочка", "Папулька",
    ],
}

MOTHER = {
    "full_name": "Клименко Марина Федоровна",
    "short_name": "Марина",
    "role": "Мамочка",
    "birth_date": date(1997, 9, 12),
    "weight_kg": 50,
    "blood_type": "не уверена",
    "allergies": [],
    "medical_history": [],
    "lactating": True,   # Важно для расчёта доз и совместимости лекарств
    "schedule": "в декрете, всегда дома",
    "nicknames": [
        "Маришка", "Маришечка", "Мариша",
        "Киця", "Кися", "Кисуля",
        "Жена", "Жёна", "Женушка",
        "Мам", "Мамуля", "Мамочка",
    ],
}

HELPERS = [
    {"role": "Бабушка С.", "full_name": "Бабушка Светлана (мама Марины)"},
    {"role": "Бабушка А.", "full_name": "Бабушка Алёна (мама Евгения)"},
]


# ─────────────────────────────────────────────────────────────────────
# Семейные даты — дни рождения и годовщины
# Используются ежедневным джобом anniversaries.py для поздравлений
# в чат, и попадают в family_context_block так что любой агент в курсе.
# ─────────────────────────────────────────────────────────────────────

FAMILY_ANNIVERSARIES = [
    {
        "date": date(1996, 6, 18),
        "kind": "birthday",
        "person": "Евгений",
        "label": "День рождения Евгения",
        "emoji": "🎂",
    },
    {
        "date": date(1997, 9, 12),
        "kind": "birthday",
        "person": "Марина",
        "label": "День рождения Марины",
        "emoji": "🎂",
    },
    {
        "date": date(2025, 12, 2),
        "kind": "birthday",
        "person": "Матвей",
        "label": "День рождения Матвея",
        "emoji": "🎂",
    },
    {
        "date": date(2019, 11, 4),
        "kind": "relationship",
        "person": "Евгений+Марина",
        "label": "Начало отношений (Евгений и Марина)",
        "emoji": "💞",
    },
    {
        "date": date(2022, 7, 30),
        "kind": "wedding",
        "person": "Евгений+Марина",
        "label": "Годовщина свадьбы",
        "emoji": "💍",
    },
]


def upcoming_anniversaries(within_days: int = 14, today=None) -> list[dict]:
    """Return dates falling in the next `within_days` days from today,
    annotated with the year-count if they occur on the actual day."""
    from datetime import date as _date, timedelta as _td
    today = today or _date.today()
    out = []
    for a in FAMILY_ANNIVERSARIES:
        # Project this year and next year to handle Dec→Jan wrap
        for year in (today.year, today.year + 1):
            try:
                proj = a["date"].replace(year=year)
            except ValueError:
                # 29 February in non-leap year
                proj = a["date"].replace(year=year, day=28)
            delta = (proj - today).days
            if 0 <= delta <= within_days:
                age_years = year - a["date"].year
                out.append({**a, "occurs_on": proj, "days_until": delta, "years": age_years})
                break
    out.sort(key=lambda x: x["days_until"])
    return out

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


# Лёгкий tracker недавних действий — обновляется откуда угодно
# (automation engine, devops handlers). Семидневное окно, тонкий sliding
# window deque.  family_context_block() читает синхронно без обращения к БД.
from collections import Counter, deque
import threading
from datetime import datetime as _dt, timedelta as _td

_ACTION_LOG: deque[tuple[_dt, str]] = deque(maxlen=500)
_ACTION_LOCK = threading.Lock()


def track_user_action(label: str) -> None:
    """Записать кодированную метку действия (e.g. «scene:Кондер 17»,
    «command:вкл бойлер»). family_context_block потом увидит частоту."""
    if not label:
        return
    with _ACTION_LOCK:
        _ACTION_LOG.append((_dt.now(), label.strip().lower()))


def _recent_patterns_block() -> str:
    """Сборка «👀 ПАТТЕРНЫ за 7 дней» из in-memory tracker'a."""
    try:
        cutoff = _dt.now() - _td(days=7)
        with _ACTION_LOCK:
            recent = [label for ts, label in _ACTION_LOG if ts >= cutoff]
        if not recent:
            return ""
        c = Counter(recent)
        top = [(label, n) for label, n in c.most_common(6) if n >= 3]
        if not top:
            return ""
        lines = ["👀 ПАТТЕРНЫ за неделю (юзер часто делает это):"]
        for label, n in top:
            lines.append(f"   • {label} — {n}×")
        lines.append(
            "Если в ТЕКУЩЕМ сообщении юзер повторяет одно из этих — "
            "можешь тёпло «узнать» («опять кондер 17?», «третий раз "
            "за неделю — комфортно?»). Без упрёка, без морализаторства. "
            "Если в текущем сообщении про эти темы нет — ИГНОРИРУЙ блок, "
            "ни в коем случае не вспоминай о них."
        )
        return "\n".join(lines)
    except Exception:
        return ""


def _family_style_memo() -> str:
    """Читает sync-кэш family_style_memo из FamilyMode. Sync чтения нет,
    поэтому кэшируем в module-global, обновляется через update_style_cache()
    из cron task."""
    return _STYLE_CACHE.get("memo", "") or ""


_STYLE_CACHE: dict[str, str] = {}


def update_style_cache(memo: str) -> None:
    _STYLE_CACHE["memo"] = (memo or "")[:4000]


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

    father_nicks = ", ".join(FATHER.get("nicknames", []))
    mother_nicks = ", ".join(MOTHER.get("nicknames", []))
    lines += [
        "",
        f"👨 Папа: {FATHER['short_name']} ({FATHER['full_name']}), {father_age}",
        f"   {FATHER['weight_kg']} кг, {FATHER['blood_type']}",
    ]
    if father_nicks:
        lines.append(f"   Прозвища (= {FATHER['short_name']}): {father_nicks}")
    lines += [
        f"   Анамнез: {'; '.join(FATHER['medical_history']) or 'без особенностей'}",
        f"   Расписание: {FATHER['schedule']}",
        "",
        f"👩 Мама: {MOTHER['short_name']} ({MOTHER['full_name']}), {mother_age}",
        f"   {MOTHER['weight_kg']} кг, группа крови {MOTHER['blood_type']}",
    ]
    if mother_nicks:
        lines.append(f"   Прозвища (= {MOTHER['short_name']}): {mother_nicks}")
    lines += [
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
    ]
    # Surface near-term family anniversaries so agents are aware without
    # needing a separate query — same source as the daily reminder job.
    soon = upcoming_anniversaries(within_days=14)
    if soon:
        lines.append("")
        lines.append("📅 Ближайшие семейные даты:")
        for a in soon[:5]:
            when = a["occurs_on"].strftime("%d.%m")
            if a["days_until"] == 0:
                tag = "🎉 СЕГОДНЯ"
            elif a["days_until"] == 1:
                tag = "завтра"
            else:
                tag = f"через {a['days_until']} дн"
            lines.append(f"   {a['emoji']} {when} ({tag}) — {a['label']} · {a['years']}-летие")
    lines.append("═══")
    # Recent patterns — что юзер делал часто за последнюю неделю.
    # Даёт агентам возможность «заметить»: «Опять кондер на 17? Третий
    # день подряд» / «Уже четвёртый раз заказываешь ту же пиццу за
    # неделю». Не для упрёка — для тёплого узнавания.
    patterns_block = _recent_patterns_block()
    if patterns_block:
        lines.append(patterns_block)
        lines.append("═══")
    style_memo = _family_style_memo()
    if style_memo:
        lines.append("🗣 СТИЛЬ СЕМЬИ (обновляется еженедельно):")
        lines.append(style_memo)
        lines.append(
            "Адаптируй тон под того кто пишет (но без передразнивания "
            "и кривляния — мягкая подстройка)."
        )
        lines.append("═══")
    lines.append(_GLOBAL_AGENT_RULES)
    from src.prompts._team import family_wiki_block
    wiki = family_wiki_block(_WIKI_FACTS)
    if wiki:
        lines.append(wiki)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Глобальные правила поведения — применяются ко ВСЕМ агентам.
# Любой агент видит этот блок в своём системном промпте через
# family_context_block(). Это единый источник правды для «не выдумывай»,
# «отвечай по теме», «не цепляй прошлое».
# ─────────────────────────────────────────────────────────────────────

_GLOBAL_AGENT_RULES = """
═══ ЖЁСТКИЕ ПРАВИЛА ДЛЯ ВСЕХ АГЕНТОВ (нарушение = брак) ═══

1. ОТВЕЧАЙ ТОЛЬКО НА ТЕКУЩЕЕ СООБЩЕНИЕ.
   История чата нужна тебе для ПОНИМАНИЯ контекста (кто такая Марина,
   что было раньше) — а НЕ для того чтобы «дополнить» тему фактами
   из прошлых разговоров. Если юзер сейчас спросил X — отвечай про X,
   ничего больше.

2. НЕ ВЫДУМЫВАЙ ТИП СОБЫТИЯ ИЗ НАМЁКОВ.
   Любое действие, которое ты заводишь (запись в дневник, событие в
   календарь, правило автоматизации, покупка) должно быть прямо
   указано в текущем сообщении. Признаки явного указания:
     • Глагол: «купи», «запиши», «напомни», «включи», «отмени»…
     • ИЛИ структурированная фраза «<дата> <дело> <время>».
   Ласковое обращение, восклицание, вопрос без действия — это НЕ
   повод что-то записывать.

   Реальный пример (что нельзя делать):
     Сообщение: «У любимой Маришки!»
     ❌ НЕВЕРНО: создать «Визит к стоматологу (Марина)»
     ✅ ВЕРНО: либо молчать (это просто эмоция), либо коротко
              переспросить «Что именно записать?»

3. НЕ ВТЯГИВАЙ ПРЕДЫДУЩИЕ ТЕМЫ.
   Если в прошлом сообщении говорили про Х, а в текущем про Y —
   отвечай про Y. Не упоминай Х «по поводу...» — это шум. Особенно
   запрещено: «По поводу баланса/Киевстара/Финна/предыдущего вопроса…»
   если юзер сейчас НЕ спросил про это.

   Запрещено также **повторно вызывать инструмент** из предыдущей темы,
   подменяя им текущий запрос:

     ❌ Юзер раньше: «в 13:00 возвращаемся домой» → ты вызвал schedule_homecoming.
        Юзер сейчас: «проверь и включи кондиционер».
        НЕВЕРНО: снова вызвать schedule_homecoming. Запрос про КОНДИЦИОНЕР,
                 а не про возвращение.
        ВЕРНО: вызови smart_sensor_read (статус) + control_smart_device
               (включи), без всякого homecoming.

     ❌ Юзер раньше: «запиши гречку в прикорм» → ты вызвал write_feeding.
        Юзер сейчас: «как сегодня кушал малыш?».
        НЕВЕРНО: снова вызвать write_feeding (он не хотел записать!).
        ВЕРНО: вызвать get_introduced_foods/get_baby_diary и рассказать.

     ❌ Юзер вчера: «какой курс доллара?» → ты ответил «спроси у Финна».
        Юзер сейчас: «включи кондер».
        НЕВЕРНО: ответить «✅ Включил. По поводу курса валют — это к Финну».
        ВЕРНО: «✅ Кондер включил». ВСЁ. Никакой валюты. Никакого Финна.
               Тема валюты закрыта вчера, в текущем сообщении её нет.

   ПРАВИЛО: если в ТЕКУЩЕМ сообщении юзера НЕТ упоминания темы X —
   ты НЕ упоминаешь X. Даже если X была в предыдущих сообщениях.
   Не «во-вторых», не «кстати», не «по поводу», не «не моя зона».
   ТИШИНА по непрошенным темам.

4. ПЕРЕСПРОСИ ЕСЛИ НЕЯСНО.
   Если в сообщении неоднозначность — задай ОДИН короткий вопрос
   («📅 Что записать — день, время, повод?»). Это лучше, чем
   выдуманное действие.

5. КОНТЕКСТ ПРОФИЛЯ СЕМЬИ — РЕФЕРЕНС, НЕ ПОВОД ГОВОРИТЬ.
   То что у Жени был туберкулёз, у Марины 50 кг и кормит грудью,
   у Матвея 6 месяцев — всё это для ПРАВИЛЬНОЙ работы. Не вставляй
   эту информацию в ответ если юзер сейчас про это не спросил.

6. ИСТОРИЯ — БАЗА ДЛЯ ИМЁН, ОТНОШЕНИЙ, ФАКТОВ.
   Если в текущем сообщении упомянута «Маришка», «Киця», «жена» —
   это Марина (см. прозвища в профиле). Если «Женя», «муж», «папа» —
   это Евгений. Используй эти связи для ПОНИМАНИЯ кто и о ком, но
   действия строй только по текущему сообщению.

7. НЕ ПРИПИСЫВАЙ СЕБЕ ДЕЙСТВИЯ КОТОРЫЕ ТЫ НЕ ДЕЛАЛ.
   Если на «спасибо» отвечает агент Y, а действие сделал агент X —
   агент Y НЕ ПИШЕТ «выключила/включила/записала», потому что **не он**
   это делал. Правильный ответ: «Пожалуйста!» или «На здоровье»,
   без приписывания себе чужой работы.

   Реальный пример нарушения:
     Прораб: «Запустил сцену Кондер 17» (кондер ВКЛЮЧЕН)
     Юзер: «Спасибули!»
     ❌ Няня: «Пожалуйста! ❤️ Кондиционер выключила.»
        → 1) выключения не было, был ВКЛ;
        → 2) делала это не Няня, а Прораб.
     ✅ Кто бы ни отвечал на «спасибо» — НЕ упоминай конкретное
        действие. Только «Пожалуйста!» / «Всегда рада!» / «Обращайся!».

8. ОБРАЩАЙСЯ ПО ИМЕНИ — ИНОГДА, НЕ КАЖДОЕ СООБЩЕНИЕ.
   В контексте сообщений ты видишь префикс автора:
     «Евгений: включи кондер»   → пишет Евгений
     «Марина: спасибули»         → пишет Марина
   Иногда (примерно раз в 3-5 сообщений) обращайся по имени —
   «Женя, готово», «Марина, держи». Это делает разговор живее,
   но КАЖДЫЙ раз — раздражает. Соблюдай меру.

9. ПОДДЕРЖИВАЙ РАЗГОВОР КОГДА УМЕСТНО.
   После основного ответа можешь иногда (НЕ всегда) добавить:
   • Уточняющий вопрос: «Кондер 17 — на сколько часов планируешь?»
   • Тёплый вопрос: «Марина, ты как сама после ночи?»
   • Совет с вопросом: «Хочешь сразу автоматизацию каждый вечер в 19:00?»
   Это не обязательно, не заваливай юзера вопросами. Один на 3-4
   ответа, когда правда уместно.

10. ССЫЛАЙСЯ НА ТО ЧТО СКАЗАЛ ДРУГОЙ АГЕНТ В ПОСЛЕДНЕМ КОНТЕКСТЕ.
   В истории чата ты видишь сообщения других агентов с префиксом
   [agent_id]. Если в текущей ситуации это РЕАЛЬНО уместно — можешь
   сослаться. «Дозорный говорил что на улице +32 — кондер в самый
   раз». Без принудительного связывания, только когда сама связь
   очевидна и полезна.

ПРИНЦИП: пп 8-10 — это специи, не основное блюдо. Применяй когда
делает разговор живее. Не превращай каждый ответ в «дружескую беседу».
═══
"""
