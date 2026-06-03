from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent
from src.utils.baby import matvey_age_months, matvey_age_human

log = structlog.get_logger()

class CookAgent(BaseAgent):
    """Гурман — recipes, baby food introduction tracking, web search for recipes."""

    agent_id = "cook"
    emoji = "🍳"
    name = "Гурман"

    def __init__(self, *args, web_search=None, sheets_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._search = web_search
        self._sheets = sheets_client

    def get_system_prompt(self) -> str:
        from src.prompts.cook import get_cook_prompt
        return get_cook_prompt(introduced_foods=[], baby_age_months=matvey_age_months(), age_human=matvey_age_human())

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
            {
                "name": "write_cooking_note",
                "description": "Записать короткое наблюдение в лист «Заметки» (для свободных мыслей и идей).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Текст заметки"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "write_feeding",
                "description": "Записать в лист «Прикорм» — твой основной журнал по питанию малыша. Используй для: новых продуктов прикорма, перекусов, рецептов которые приготовили, реакции на еду. ВАЖНО: для базового события «съел X» в общий Дневник пишет Няня, ты дополняешь в «Прикорм» с деталями реакции/порции.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "Тип: Прикорм / Перекус / Рецепт / Напиток / Десерт / Другое"},
                        "product": {"type": "string", "description": "Название продукта/блюда («Кабачок», «Брокколи в пюре», «Овсяная каша»)"},
                        "portion": {"type": "string", "description": "Порция: «1/2 ч.л.», «100 мл», «1 ст.л.»"},
                        "reaction": {"type": "string", "description": "Реакция: Отличная / Хорошая / Нейтральная / Отказался / Сыпь / Аллергия"},
                        "details": {"type": "string", "description": "Подробности: способ приготовления, рецепт, наблюдения"},
                    },
                    "required": ["type", "product"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "write_cooking_note":
            if not self._sheets:
                return {"error": "Google Sheets не настроен"}
            from src.utils.time import now_kyiv
            author = getattr(self, "_current_sender", "") or "Гурман"
            return await self._sheets.append_note(
                text=tool_input.get("text", ""),
                time=now_kyiv(),
                author=author,
            )

        if tool_name == "write_feeding":
            if not self._sheets:
                return {"error": "Google Sheets не настроен"}
            from src.utils.time import now_kyiv
            author = getattr(self, "_current_sender", "") or "Гурман"
            return await self._sheets.append_feeding(
                type_=tool_input.get("type", "Прикорм"),
                product=tool_input.get("product", ""),
                time=now_kyiv(),
                portion=tool_input.get("portion", ""),
                reaction=tool_input.get("reaction", ""),
                details=tool_input.get("details", ""),
                author=author,
            )

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
