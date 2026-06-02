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

        return await super()._call_tool(tool_name, tool_input)
