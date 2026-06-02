from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent
from src.utils.baby import matvey_age_months

log = structlog.get_logger()

class CookAgent(BaseAgent):
    """Гурман — recipes, baby food introduction tracking, web search for recipes."""

    agent_id = "cook"
    emoji = "🍳"
    name = "Гурман"

    def __init__(self, *args, web_search=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._search = web_search

    def get_system_prompt(self) -> str:
        from src.prompts.cook import get_cook_prompt
        return get_cook_prompt(introduced_foods=[], baby_age_months=matvey_age_months())

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "description": "Поиск рецептов в интернете",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "log_new_food",
                "description": "Записать новый продукт прикорма",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "food": {"type": "string"},
                        "reaction": {"type": "string", "enum": ["ok", "rash", "rejected", "unknown"]},
                        "notes": {"type": "string"},
                    },
                    "required": ["food"],
                },
            },
            {
                "name": "get_introduced_foods",
                "description": "Посмотреть что малыш уже пробовал",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "web_search" and self._search:
            results = await self._search.search(tool_input["query"])
            return [{"title": r.title, "snippet": r.snippet, "url": r.url} for r in results[:3]]

        elif tool_name == "log_new_food":
            from src.utils.time import iso_now
            async with self._memory._engine.begin() as conn:
                from src.db.models import IntroducedFood
                from sqlalchemy import insert
                await conn.execute(
                    insert(IntroducedFood).prefix_with("OR REPLACE").values(
                        food=tool_input["food"],
                        first_tried_at=iso_now(),
                        reaction=tool_input.get("reaction", "unknown"),
                        notes=tool_input.get("notes"),
                    )
                )
            return {"success": True}

        elif tool_name == "get_introduced_foods":
            async with self._memory._engine.connect() as conn:
                from src.db.models import IntroducedFood
                from sqlalchemy import select
                rows = await conn.execute(select(IntroducedFood).order_by(IntroducedFood.first_tried_at.desc()))
                return [{"food": r.food, "reaction": r.reaction, "tried": r.first_tried_at} for r in rows]

        return await super()._call_tool(tool_name, tool_input)
