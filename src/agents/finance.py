from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger()

class FinanceAgent(BaseAgent):
    """Казначей — tracks family expenses and budgets."""

    agent_id = "finance"
    emoji = "💰"
    name = "Казначей"

    def __init__(self, *args, sheets_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sheets = sheets_client

    def get_system_prompt(self) -> str:
        from src.prompts.finance import get_finance_prompt
        return get_finance_prompt()

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "append_expense",
                "description": "Записать расход в Google Sheets",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "member": {"type": "string", "enum": ["Я", "Жена", "Малыш"], "default": "Я"},
                    },
                    "required": ["amount", "category", "description"],
                },
            },
            {
                "name": "get_monthly_summary",
                "description": "Получить итоги за месяц по категориям",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer"},
                        "month": {"type": "integer"},
                    },
                },
            },
            {
                "name": "get_expenses",
                "description": "Получить список расходов за период",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 30},
                        "category": {"type": "string"},
                    },
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        from src.utils.time import now_kyiv

        if tool_name == "append_expense" and self._sheets:
            row = await self._sheets.append_expense(
                amount=tool_input["amount"],
                category=tool_input["category"],
                description=tool_input["description"],
                date=now_kyiv(),
                member=tool_input.get("member", "Я"),
            )
            return {"success": True, "row": row.row_index}

        elif tool_name == "get_monthly_summary" and self._sheets:
            now = now_kyiv()
            summary = await self._sheets.get_monthly_budget_summary(
                year=tool_input.get("year", now.year),
                month=tool_input.get("month", now.month),
            )
            return summary

        elif tool_name == "get_expenses" and self._sheets:
            rows = await self._sheets.get_expenses(
                days=tool_input.get("days", 30),
                category=tool_input.get("category"),
            )
            return [r.data for r in rows[-30:]]

        return {"success": False, "note": "sheets not configured"}
