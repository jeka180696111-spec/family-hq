"""Daily anniversaries job — runs at 08:00 Kyiv.

Behaviour:
  • If TODAY matches any entry in FAMILY_ANNIVERSARIES → send one
    consolidated congratulation in the voice of multiple agents,
    posted by Прораб to keep the chat tidy.
  • If an anniversary is 1, 3 or 7 days AHEAD → send a heads-up so
    Eugene/Marina don't forget to prepare a gift or call grandma.

The job is idempotent thanks to the FamilyEvent table — we mark each
(date, kind) as "sent" so a Railway restart at 08:15 doesn't double-fire.
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Any

import structlog

from src.utils.family import FAMILY_ANNIVERSARIES, upcoming_anniversaries

log = structlog.get_logger()


# Per-agent congratulation templates. {years}, {who} are interpolated.
_BIRTHDAY_LINES = {
    "Евгений": [
        ("Няня", "Папочка, с днём рождения! Матвей сегодня обнимает тебя крепче обычного 🤱"),
        ("Гурман", "Сегодня твой день — заказывай что хочешь, ужин на тебе не лежит 🍳"),
        ("Айболит", "С праздником! Береги себя — ты семье ОЧЕНЬ нужен. Особенно после года восстановления 💪"),
        ("Дозорный", "🎂 Поздравляю! Сегодня все тревоги ставлю на паузу, пусть день будет спокойный."),
    ],
    "Марина": [
        ("Няня", "Мамочка, с днём рождения! Самой нежной маме в мире — много счастья 💝"),
        ("Гурман", "Сегодня твой день отдыха — ужин и кофе организую без тебя ☕"),
        ("Айболит", "С праздником! Береги силы, ты главная опора Матвея. И помни про себя 🌸"),
        ("Ежедневник", "📅 Сегодня в календаре только один пункт — ТЫ. Всё остальное переношу."),
    ],
    "Матвей": [
        ("Няня", "Матвейка, с днём рождения! Ты у нас самый чудесный малыш 🍼"),
        ("Гурман", "Сегодня испечём что-то особенное по возрасту — пюре будет с праздничным украшением 🎂"),
        ("Айболит", "Расти большой и здоровый, малыш! Мы все следим за тобой 🌱"),
        ("Дозорный", "📸 Сделайте сегодня кучу фото — для хроники этот день войдёт на видное место."),
    ],
}

_RELATIONSHIP_LINES = [
    ("Няня", "С годовщиной отношений! Спасибо что сделали такую тёплую семью, в которой Матвей растёт счастливым 💞"),
    ("Гурман", "Сегодня — ваш вечер. Ужин при свечах организуем (бабушку для Матвея — позовём заранее) 🍷"),
    ("Дозорный", "💞 {years} лет вместе — и ещё много впереди. Поздравляю!"),
]

_WEDDING_LINES = [
    ("Няня", "С годовщиной свадьбы! Вы — самая лучшая пара родителей которых мог бы попросить Матвей 💍"),
    ("Гурман", "Сегодня готовлю особенное меню. Стол накрою — оставьте время вечером 🍾"),
    ("Айболит", "{years} лет в браке — рекомендую сегодня выходной от тревог. И больше обнимашек 🤗"),
    ("Дозорный", "💍 {years} лет вместе — настоящее достижение в наше время. Поздравляю!"),
]


def _compose_birthday(person: str, years: int) -> str:
    lines = _BIRTHDAY_LINES.get(person)
    if not lines:
        return f"🎂 {person} — с днём рождения! {years}-летие."
    out = [f"🎂 <b>Сегодня день рождения у {person}!</b>", f"<i>{years}-летие 🎉</i>", ""]
    for agent, text in lines:
        out.append(f"<b>{agent}</b>: {text.format(years=years, who=person)}")
    return "\n".join(out)


def _compose_relationship(years: int, kind: str) -> str:
    if kind == "wedding":
        tpl = _WEDDING_LINES
        title = f"💍 <b>{years}-летие свадьбы!</b>"
    else:
        tpl = _RELATIONSHIP_LINES
        title = f"💞 <b>{years} лет вместе!</b>"
    out = [title, ""]
    for agent, text in tpl:
        out.append(f"<b>{agent}</b>: {text.format(years=years)}")
    return "\n".join(out)


async def _already_sent(memory, marker: str) -> bool:
    from sqlalchemy import select
    from src.db.models import EventLog
    async with memory._engine.connect() as conn:
        row = (await conn.execute(
            select(EventLog).where(EventLog.event == "anniv_sent").where(
                EventLog.payload == marker
            ).limit(1)
        )).first()
    return row is not None


async def _mark_sent(memory, marker: str) -> None:
    from sqlalchemy import insert
    from src.db.models import EventLog
    from src.utils.time import iso_now
    async with memory._engine.begin() as conn:
        await conn.execute(insert(EventLog).values(
            event="anniv_sent", payload=marker,
            created_at=iso_now(), agent_id="devops",
        ))


async def daily_anniversary_check(
    bot_manager: Any, chat_id: int, memory: Any,
) -> None:
    """Single entry-point — runs once per day at 08:00 Kyiv."""
    today = _date.today()

    # 1) Today's anniversaries — composite congrats
    for a in FAMILY_ANNIVERSARIES:
        try:
            this_year = a["date"].replace(year=today.year)
        except ValueError:
            this_year = a["date"].replace(year=today.year, day=28)
        if this_year != today:
            continue
        years = today.year - a["date"].year
        marker = f"{today.isoformat()}:{a['kind']}:{a['person']}"
        if await _already_sent(memory, marker):
            continue
        if a["kind"] == "birthday":
            text = _compose_birthday(a["person"], years)
        else:
            text = _compose_relationship(years, a["kind"])
        try:
            await bot_manager.send_message(
                agent_id="devops", chat_id=chat_id, text=text,
            )
            await _mark_sent(memory, marker)
            log.info("anniversary_congrats_sent", marker=marker)
        except Exception:
            log.exception("anniversary_send_failed", marker=marker)

    # 2) Heads-up reminders — fire on D-7, D-3 and D-1.
    soon = upcoming_anniversaries(within_days=7, today=today)
    for a in soon:
        days = a["days_until"]
        if days not in (7, 3, 1):
            continue
        marker = f"prewarn:{a['occurs_on'].isoformat()}:{a['kind']}:{a['person']}:{days}"
        if await _already_sent(memory, marker):
            continue
        when_label = "через неделю" if days == 7 else "через 3 дня" if days == 3 else "завтра"
        msg = (
            f"🔔 <b>Напоминание</b>\n"
            f"{when_label}: {a['emoji']} {a['label']} ({a['years']}-летие, {a['occurs_on'].strftime('%d.%m')})\n\n"
        )
        if a["kind"] == "birthday":
            msg += "Подумай про подарок/торт/звонок 🎁"
        elif a["kind"] == "wedding":
            msg += "Подумай про ресторан или особенный ужин 💍"
        else:
            msg += "Подумай как отметите 💞"
        try:
            await bot_manager.send_message(
                agent_id="devops", chat_id=chat_id, text=msg,
            )
            await _mark_sent(memory, marker)
            log.info("anniversary_prewarn_sent", marker=marker)
        except Exception:
            log.exception("anniversary_prewarn_send_failed", marker=marker)


def register_anniversary_job(scheduler, bot_manager: Any, chat_id: int, memory: Any) -> None:
    scheduler.add_job(
        daily_anniversary_check,
        "cron", hour=8, minute=0, timezone="Europe/Kiev",
        args=[bot_manager, chat_id, memory],
        id="anniversary_check", replace_existing=True,
    )
    log.info("anniversary_job_registered")
