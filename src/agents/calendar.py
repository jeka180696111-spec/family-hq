from __future__ import annotations
from typing import Any
from datetime import datetime
import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger()

class CalendarAgent(BaseAgent):
    """Ежедневник — manages Google Calendar events and reminders."""

    agent_id = "calendar"
    emoji = "📅"
    name = "Ежедневник"

    def __init__(self, *args, calendar_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._calendar = calendar_client

    def get_system_prompt(self) -> str:
        from src.prompts.calendar import get_calendar_prompt
        return get_calendar_prompt()

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "create_event",
                "description": "Создать событие в Google Calendar",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start_iso": {"type": "string", "description": "ISO datetime"},
                        "end_iso": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "list_upcoming",
                "description": "Показать предстоящие события",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "default": 7},
                    },
                },
            },
            {
                "name": "find_events",
                "description": "Найти события по запросу",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if not self._calendar:
            return {"note": "calendar not configured"}

        if tool_name == "create_event":
            start = None
            if tool_input.get("start_iso"):
                try:
                    start = datetime.fromisoformat(tool_input["start_iso"])
                except ValueError:
                    pass
            if not start:
                from src.utils.time import now_kyiv
                start = now_kyiv()

            event = await self._calendar.create_event(
                title=tool_input["title"],
                start=start,
                description=tool_input.get("description", ""),
            )
            return {"event_id": event.event_id, "title": event.title}

        elif tool_name == "list_upcoming":
            events = await self._calendar.list_upcoming(days=tool_input.get("days", 7))
            return [{"title": e.title, "start": e.start.isoformat()} for e in events]

        elif tool_name == "find_events":
            events = await self._calendar.find_events(tool_input["query"])
            return [{"title": e.title, "start": e.start.isoformat(), "id": e.event_id} for e in events]

        return await super()._call_tool(tool_name, tool_input)
