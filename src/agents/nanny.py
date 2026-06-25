from __future__ import annotations
from typing import Any, TYPE_CHECKING
import structlog

from src.agents.base import BaseAgent
from src.db.models import FamilyMember, HealthRecord
from src.utils.baby import MATVEY_BIRTH_DATE, matvey_age_months, matvey_age_human

if TYPE_CHECKING:
    from src.integrations.sheets import SheetsClient
    from src.db.memory import SharedMemory

log = structlog.get_logger()

class NannyAgent(BaseAgent):
    """
    Няня — tracks baby Matvey: sleep, food, medicine, development.
    Reads/writes Google Sheets Matveika diary.
    """

    agent_id = "nanny"
    emoji = "🤱"
    name = "Няня"

    def __init__(self, *args, sheets_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sheets = sheets_client

    def get_system_prompt(self) -> str:
        from src.prompts.nanny import get_nanny_prompt
        return get_nanny_prompt(
            birth_date=MATVEY_BIRTH_DATE.strftime("%d.%m.%Y"),
            age_months=matvey_age_months(),
            age_human=matvey_age_human(),
            weight_kg=None,
            allergies=[],
            introduced_foods=[],
        )

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "write_baby_diary",
                "description": "Записать событие в дневник малыша в Google Sheets",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["sleep", "food", "diaper", "walk", "trip", "medicine", "symptom", "milestone", "note"]},
                        "event": {"type": "string", "description": "Описание события"},
                        "time": {"type": "string", "description": "Время в формате HH:MM или 'now'"},
                        "amount": {"type": "number"},
                        "unit": {"type": "string"},
                        "details": {"type": "string"},
                    },
                    "required": ["kind", "event"],
                },
            },
            {
                "name": "read_baby_diary",
                "description": "Прочитать записи дневника малыша",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 7},
                        "kind": {"type": "string"},
                    },
                },
            },
            {
                "name": "ask_user",
                "description": "Задать уточняющий вопрос пользователю",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "write_note",
                "description": "Записать заметку в лист «Заметки» — для текстовых наблюдений, не подходящих под Дневник (мысли, забавности, ситуации).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "time": {"type": "string", "description": "HH:MM или 'now'"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "write_milestone",
                "description": "Записать достижение в лист «Достижения» (первый раз, навык, веха). Возраст подставится автоматически.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "milestone": {"type": "string", "description": "Короткое название: Перевернулся, Пополз, Первый зуб, Сел сам, Пошёл, Улыбнулся, Первое слово или Другое"},
                        "details": {"type": "string", "description": "Подробности (опционально)"},
                    },
                    "required": ["milestone"],
                },
            },
            {
                "name": "who_check",
                "description": (
                    "Сравнить вес/рост Матвея с нормами ВОЗ и вернуть перцентиль. "
                    "Вызывай КАЖДЫЙ РАЗ когда пишут новый вес или рост и после write_growth."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "weight_kg": {"type": "number"},
                        "height_cm": {"type": "number"},
                    },
                },
            },
            {
                "name": "write_growth",
                "description": "Записать измерение веса и/или роста в лист «Рост». Минимум одно из weight_g или height_cm.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "weight_g": {"type": "integer", "description": "Вес в граммах (например 8000 = 8 кг)"},
                        "height_cm": {"type": "number", "description": "Рост в сантиметрах"},
                        "details": {"type": "string"},
                    },
                },
            },
            {
                "name": "write_health",
                "description": "Записать медицинское событие в лист «Здоровье»: лекарство, симптом, рвота, плач, беспокойный сон.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "Лекарство / Симптом / Рвота / Сильный плач / Сон беспокойный / Температура / Сыпь / Кашель / Другое"},
                        "name": {"type": "string", "description": "Название препарата или симптома (для Лекарство: «Витамин Д», «Эспумизан», «Нурофен»; для Симптом: то же что и type)"},
                        "value": {"type": "string", "description": "Количество/значение если есть, например '2.5 мл', '37.8'"},
                        "details": {"type": "string"},
                        "time": {"type": "string", "description": "HH:MM или 'now'"},
                    },
                    "required": ["type", "name"],
                },
            },
            {
                "name": "write_doctor",
                "description": "Записать визит к врачу / прививку в лист «Врач».",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "Прививка / Осмотр / Анализ / УЗИ / Консультация / Другое"},
                        "name": {"type": "string", "description": "Что именно: «БЦЖ», «Инфанрикс гекса», «педиатр», «Общий анализ крови»"},
                        "next_due": {"type": "string", "description": "Когда следующее (опционально): «4 мес», «через месяц», «01.07.2026»"},
                        "details": {"type": "string"},
                    },
                    "required": ["type", "name"],
                },
            },
            {
                "name": "log_night_shift",
                "description": (
                    "Записать кто вчера/сегодня ночью был на «дежурстве» с Матвеем. "
                    "Помогает справедливо чередовать сон родителей."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "on_duty": {"type": "string", "enum": ["eugene", "marina", "both"]},
                        "notes": {"type": "string"},
                    },
                    "required": ["on_duty"],
                },
            },
            {
                "name": "whose_turn_tonight",
                "description": "Подсчитать чья очередь сегодня дежурить по предыдущим сменам.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "babysitter_handoff",
                "description": (
                    "Сформировать короткую сводку для бабушки/няни перед сменой: что было сегодня, "
                    "когда поел/спал, что ест сейчас, на что обращать внимание."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "for_helper": {"type": "string", "description": "Кому передать: Бабушка С. / Бабушка А. / няня"},
                    },
                },
            },
            {
                "name": "import_milestones_from_diary",
                "description": (
                    "Один раз: пройти по Дневнику Матвея и автоматически создать записи "
                    "«первое X» в листе Достижения. Не дублирует существующие."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "sleep_analysis",
                "description": (
                    "📊 АНАЛИЗ СНА Матвея за последние N дней + рекомендации. "
                    "Читает Дневник, считает дневной/ночной сон, время bedtime/wake, "
                    "ночные пробуждения. Возвращает age-typical wake window, "
                    "среднее текущее, и КОНКРЕТНЫЕ советы что попробовать сегодня. "
                    "Триггеры: «няня, что с сном», «анализ сна», «как Матвей спал», "
                    "«разбери его сон», «корректировка сна», «помоги со сном», "
                    "«когда укладывать», «когда буить», «можно ли спать дальше»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "За сколько дней анализ (по умолчанию 7).",
                        },
                    },
                },
            },
            {
                "name": "next_sleep_advice",
                "description": (
                    "🕐 «КОГДА следующий сон / когда будить» — для конкретной ситуации "
                    "«прямо сейчас». Читает последнюю запись Дневника, считает "
                    "сколько Матвей бодрствует/спит, и говорит: уложи в HH:MM, "
                    "буди в HH:MM, либо «спит дольше нормы — пора будить». "
                    "Триггеры: «когда укладывать», «не пора ли спать», "
                    "«пора будить», «сколько ещё ему спать», «когда следующее окно»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "recent_baby_photos",
                "description": (
                    "Показать недавние фото малыша из архива (для альбома, дайджеста бабушкам). "
                    "Триггер: «покажи фото», «архив малыша», «последние фото»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Сколько фото (по умолчанию 5)"},
                        "days_back": {"type": "integer", "description": "За сколько дней (по умолчанию 14)"},
                    },
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        from src.utils.time import now_kyiv
        from datetime import datetime

        if tool_name == "write_baby_diary":
            if self._sheets:
                time_str = tool_input.get("time", "now")
                if time_str == "now":
                    dt = now_kyiv()
                else:
                    try:
                        t = datetime.strptime(time_str, "%H:%M").time()
                        dt = now_kyiv().replace(hour=t.hour, minute=t.minute)
                    except ValueError:
                        dt = now_kyiv()

                row = await self._sheets.append_baby_diary(
                    kind=tool_input.get("kind", "note"),
                    event=tool_input.get("event", ""),
                    time=dt,
                    author=getattr(self, "_current_sender", "") or "family_hq",
                    amount=tool_input.get("amount"),
                    unit=tool_input.get("unit"),
                    details=tool_input.get("details", ""),
                )
                # Update live BabyState snapshot so automations can react fast
                try:
                    await self._update_baby_state(
                        kind=tool_input.get("kind", ""),
                        event=tool_input.get("event", ""),
                        at=dt,
                    )
                except Exception:
                    log.exception("baby_state_update_failed")
                return {"success": True, "row": row.row_index}
            return {"success": True, "note": "sheets not configured"}

        elif tool_name == "read_baby_diary":
            if self._sheets:
                rows = await self._sheets.get_baby_diary(
                    days=tool_input.get("days", 7),
                    kind=tool_input.get("kind"),
                )
                return [r.data for r in rows[-100:]]
            return []

        elif tool_name == "ask_user":
            return {"question_sent": tool_input.get("question")}

        elif tool_name == "who_check":
            from src.utils.who import weight_percentile, height_percentile
            from src.utils.baby import matvey_age_months
            age = matvey_age_months()
            result = {"age_months": age}
            w = tool_input.get("weight_kg")
            if w:
                result["weight"] = weight_percentile(float(w), age)
            h = tool_input.get("height_cm")
            if h:
                result["height"] = height_percentile(float(h), age)
            if not w and not h:
                return {"error": "укажи weight_kg или height_cm"}
            return result

        elif tool_name in ("write_note", "write_milestone", "write_growth", "write_health", "write_doctor"):
            if not self._sheets:
                return {"error": "Google Sheets не настроен"}
            time_str = tool_input.get("time", "now")
            if time_str == "now":
                dt = now_kyiv()
            else:
                try:
                    t = datetime.strptime(time_str, "%H:%M").time()
                    dt = now_kyiv().replace(hour=t.hour, minute=t.minute)
                except ValueError:
                    dt = now_kyiv()
            author = getattr(self, "_current_sender", "") or "family_hq"

            if tool_name == "write_note":
                return await self._sheets.append_note(
                    text=tool_input.get("text", ""),
                    time=dt,
                    author=author,
                )
            if tool_name == "write_milestone":
                return await self._sheets.append_milestone(
                    milestone=tool_input.get("milestone", ""),
                    time=dt,
                    details=tool_input.get("details", ""),
                    author=author,
                )
            if tool_name == "write_growth":
                return await self._sheets.append_growth(
                    weight_g=tool_input.get("weight_g"),
                    height_cm=tool_input.get("height_cm"),
                    time=dt,
                    details=tool_input.get("details", ""),
                )
            if tool_name == "write_health":
                return await self._sheets.append_health(
                    type_=tool_input.get("type", ""),
                    name=tool_input.get("name", ""),
                    time=dt,
                    value=tool_input.get("value", ""),
                    details=tool_input.get("details", ""),
                )
            if tool_name == "write_doctor":
                return await self._sheets.append_doctor(
                    type_=tool_input.get("type", ""),
                    name=tool_input.get("name", ""),
                    time=dt,
                    next_due=tool_input.get("next_due", ""),
                    details=tool_input.get("details", ""),
                )

        if tool_name == "log_night_shift":
            from datetime import date
            from sqlalchemy import insert
            from src.db.models import NightShift
            async with self._memory._engine.begin() as conn:
                await conn.execute(insert(NightShift).values(
                    date=date.today().isoformat(),
                    on_duty=tool_input["on_duty"],
                    notes=tool_input.get("notes"),
                ))
            return {"success": True, "on_duty": tool_input["on_duty"]}

        if tool_name == "whose_turn_tonight":
            from sqlalchemy import select
            from src.db.models import NightShift
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(NightShift).order_by(NightShift.date.desc()).limit(14)
                ))
            counts = {"eugene": 0, "marina": 0}
            for r in rows:
                if r.on_duty in counts:
                    counts[r.on_duty] += 1
            last = rows[0].on_duty if rows else None
            # Whoever had fewer turns OR opposite of last
            if counts["eugene"] < counts["marina"]:
                rec = "eugene"
            elif counts["marina"] < counts["eugene"]:
                rec = "marina"
            else:
                rec = "marina" if last == "eugene" else "eugene"
            return {
                "last_two_weeks": counts,
                "last_on_duty": last,
                "recommended_tonight": rec,
                "reason": "по балансу смен за 2 недели",
            }

        if tool_name == "babysitter_handoff":
            from datetime import timedelta
            from src.integrations.history_search import _search_sheet
            from src.utils.time import now_kyiv
            now = now_kyiv()
            cutoff = now - timedelta(hours=12)
            diary = []
            if self._sheets:
                try:
                    diary = await _search_sheet(self._sheets, "Дневник", "", cutoff, 100)
                except Exception:
                    pass
            import json as _json
            prompt = (
                "Сформируй короткую сводку для бабушки/няни «что было с малышом сегодня». "
                "Структура: 😴 последний сон (когда лёг/проснулся, длительность), "
                "🍼 последнее кормление (когда, чем), 💧 подгузники (когда последний раз, что), "
                "📋 что важно: режим/симптомы/нужно дать лекарство/время следующего кормления. "
                "Кратко, по существу.\n\n"
                f"ЗАПИСИ:\n{_json.dumps(diary, ensure_ascii=False, default=str)[:3000]}"
            )
            resp = await self._claude.complete(
                model=self._get_model(),
                system="Ты — Няня. Передаёшь смену помощнику. Тёплый, конкретный тон.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
            return {"handoff_text": resp.strip(), "for": tool_input.get("for_helper", "помощнику")}

        if tool_name == "import_milestones_from_diary":
            return await self._import_milestones()

        if tool_name == "recent_baby_photos":
            return await self._recent_baby_photos(
                limit=int(tool_input.get("limit", 5)),
                days_back=int(tool_input.get("days_back", 14)),
            )

        if tool_name == "sleep_analysis":
            from src.integrations.sleep_coach import weekly_analysis
            if not self._sheets:
                return {"error": "Sheets не подключены"}
            try:
                return await weekly_analysis(
                    self._sheets,
                    days=int(tool_input.get("days", 7)),
                )
            except Exception as e:
                return {"error": f"sleep_analysis failed: {type(e).__name__}: {e}"}

        if tool_name == "next_sleep_advice":
            from src.integrations.sleep_coach import next_sleep_advice
            if not self._sheets:
                return {"error": "Sheets не подключены"}
            try:
                return await next_sleep_advice(self._sheets)
            except Exception as e:
                return {"error": f"next_sleep_advice failed: {type(e).__name__}: {e}"}

        return await super()._call_tool(tool_name, tool_input)

    async def _update_baby_state(self, kind: str, event: str, at) -> None:
        """Project diary write into BabyState row(1) for fast automation lookup."""
        from sqlalchemy import insert, select
        from sqlalchemy import update as sql_update
        from src.db.models import BabyState
        from src.utils.time import iso_now
        kind_l = (kind or "").lower()
        event_l = (event or "").lower()
        ts = at.isoformat() if hasattr(at, "isoformat") else str(at)
        async with self._memory._engine.begin() as conn:
            row = (await conn.execute(select(BabyState).where(BabyState.id == 1))).first()
            values: dict[str, str | None] = {"updated_at": iso_now()}
            if kind_l == "sleep":
                if any(w in event_l for w in ("уснул", "уснула", "усн", "начал спать", "спит", "лёг", "лег")):
                    values["sleeping_since"] = ts
                    values["awake_since"] = None
                elif any(w in event_l for w in ("проснул", "встал", "разбудил", "не спит", "поел", "просыпан")):
                    values["awake_since"] = ts
                    values["sleeping_since"] = None
            if kind_l == "food":
                values["last_feed_at"] = ts
            if kind_l == "diaper":
                values["last_diaper_at"] = ts
            if kind_l in ("walk", "trip"):
                if any(w in event_l for w in (
                    "вышли", "вышел", "вышла", "выехали", "пошли", "идём гулять",
                    "пошли гулять", "на прогулк", "началась прогулк",
                )):
                    values["walking_since"] = ts
                    values["walk_ended_at"] = None
                elif any(w in event_l for w in (
                    "вернулись", "вернулся", "пришли", "пришёл", "пришла",
                    "приехали", "закончили", "конец прогулк", "дома",
                )):
                    values["walk_ended_at"] = ts
                    values["walking_since"] = None
                else:
                    # ambiguous walk write — assume start if no current walk
                    values["walking_since"] = ts
                    values["walk_ended_at"] = None
            if row:
                await conn.execute(sql_update(BabyState).where(BabyState.id == 1).values(**values))
            else:
                await conn.execute(insert(BabyState).values(id=1, **values))

    async def _recent_baby_photos(self, limit: int, days_back: int) -> dict:
        from datetime import timedelta
        from sqlalchemy import select
        from src.db.models import BabyPhoto
        from src.utils.time import now_kyiv
        cutoff = (now_kyiv() - timedelta(days=days_back)).isoformat()
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(BabyPhoto).where(BabyPhoto.created_at >= cutoff)
                .order_by(BabyPhoto.id.desc()).limit(max(1, min(50, limit)))
            ))
        return {
            "count": len(rows),
            "photos": [
                {
                    "id": r.id, "age": r.age_label, "caption": r.caption,
                    "drive_file_id": r.drive_file_id, "created_at": r.created_at,
                } for r in rows
            ],
        }

    async def _import_milestones(self) -> dict:
        """Scan Дневник + Прикорм for 'first occurrence' events and append to Достижения."""
        if not self._sheets:
            return {"error": "Sheets не настроен"}
        from datetime import datetime
        from src.integrations.history_search import _search_sheet

        # Pull existing milestones to avoid duplicates
        try:
            existing = await _search_sheet(self._sheets, "Достижения", "", datetime(2020, 1, 1), 500)
        except Exception:
            existing = []
        seen = {(row.get("Достижение", "") or "").lower() for row in existing}

        created: list[dict] = []

        # Scan Прикорм for first occurrences of each product
        try:
            feed_rows = await _search_sheet(self._sheets, "Прикорм", "", datetime(2020, 1, 1), 1000)
        except Exception:
            feed_rows = []
        first_food: dict[str, dict] = {}
        for row in feed_rows:
            product = (row.get("Продукт") or row.get("Продукт/Блюдо") or "").strip()
            date_str = (row.get("Дата") or "").strip()
            if not product or not date_str:
                continue
            key = product.lower()
            if key in first_food:
                continue
            try:
                dt = datetime.strptime(date_str, "%d.%m.%Y")
            except ValueError:
                continue
            first_food[key] = {"product": product, "date": dt}

        for key, entry in first_food.items():
            milestone_label = f"Первый раз {entry['product']}"
            if milestone_label.lower() in seen:
                continue
            try:
                await self._sheets.append_milestone(
                    milestone="Другое",
                    time=entry["date"],
                    details=milestone_label,
                    author="Архивариус",
                )
                created.append({"date": entry["date"].strftime("%d.%m.%Y"), "milestone": milestone_label})
            except Exception:
                pass

        # Scan Дневник for first "Уснул", first "Какал", first solid food entries marked as Прикорм:
        try:
            diary_rows = await _search_sheet(self._sheets, "Дневник", "", datetime(2020, 1, 1), 2000)
        except Exception:
            diary_rows = []

        markers = {
            "Уснул": "Первое самостоятельное засыпание",
            "Какал": "Первый стул",
            "Грудь Л": "Первое кормление левой грудью",
            "Грудь П": "Первое кормление правой грудью",
            "Смесь": "Первый раз смесь",
        }
        marker_found: dict[str, datetime] = {}
        for row in diary_rows:
            event = (row.get("Тип / Детали") or row.get("Тип/Детали") or "").strip()
            for needle, label in markers.items():
                if needle in event and needle not in marker_found:
                    try:
                        dt = datetime.strptime(row.get("Дата", ""), "%d.%m.%Y")
                        marker_found[needle] = dt
                    except (KeyError, ValueError):
                        pass
                    break
        for needle, dt in marker_found.items():
            label = markers[needle]
            if label.lower() in seen:
                continue
            try:
                await self._sheets.append_milestone(
                    milestone="Другое",
                    time=dt,
                    details=label,
                    author="Архивариус",
                )
                created.append({"date": dt.strftime("%d.%m.%Y"), "milestone": label})
            except Exception:
                pass

        return {
            "imported": len(created),
            "items": created,
            "note": "Проверь лист «Достижения» — добавлены автоматически найденные первые события",
        }
