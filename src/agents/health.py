from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger()

class HealthAgent(BaseAgent):
    """Айболит — health tracking, medication info, symptom guidance."""

    agent_id = "health"
    emoji = "🏥"
    name = "Айболит"

    def get_system_prompt(self) -> str:
        from src.prompts.health import get_health_prompt
        return get_health_prompt(family_members=[])

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "log_health_event",
                "description": "Записать событие здоровья в БД",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "matvey|husband|wife"},
                        "kind": {"type": "string", "enum": ["symptom", "medication", "visit", "vaccine"]},
                        "description": {"type": "string"},
                        "value": {"type": "string", "description": "температура, доза и т.д."},
                    },
                    "required": ["member_id", "kind", "description"],
                },
            },
            {
                "name": "get_health_history",
                "description": "Получить историю здоровья члена семьи",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string"},
                        "days": {"type": "integer", "default": 30},
                    },
                    "required": ["member_id"],
                },
            },
            {
                "name": "get_medication_dose",
                "description": "Узнать дозировку лекарства по весу",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "medication": {"type": "string"},
                        "weight_kg": {"type": "number"},
                        "age_months": {"type": "integer"},
                    },
                    "required": ["medication"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        from src.utils.time import iso_now

        if tool_name == "log_health_event":
            async with self._memory._engine.begin() as conn:
                from src.db.models import HealthRecord
                from sqlalchemy import insert
                await conn.execute(
                    insert(HealthRecord).values(
                        member_id=tool_input["member_id"],
                        kind=tool_input["kind"],
                        description=tool_input["description"],
                        value=tool_input.get("value"),
                        date=iso_now(),
                    )
                )
            return {"success": True}

        elif tool_name == "get_health_history":
            async with self._memory._engine.connect() as conn:
                from src.db.models import HealthRecord
                from sqlalchemy import select
                rows = await conn.execute(
                    select(HealthRecord)
                    .where(HealthRecord.member_id == tool_input["member_id"])
                    .order_by(HealthRecord.date.desc())
                    .limit(20)
                )
                return [{"kind": r.kind, "description": r.description, "value": r.value, "date": r.date} for r in rows]

        elif tool_name == "get_medication_dose":
            # Return structured info for Claude to interpret
            return {
                "medication": tool_input["medication"],
                "note": "Дозировки предоставлены как справочная информация. Следуй инструкции к препарату.",
                "weight_kg": tool_input.get("weight_kg"),
            }

        return await super()._call_tool(tool_name, tool_input)
