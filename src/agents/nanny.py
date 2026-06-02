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
                        "kind": {"type": "string", "enum": ["sleep", "food", "medicine", "note", "symptom", "milestone"]},
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

        return await super()._call_tool(tool_name, tool_input)
