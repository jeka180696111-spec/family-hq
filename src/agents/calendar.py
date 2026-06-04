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
                "description": (
                    "Создать событие в Google Calendar. "
                    "ОБЯЗАТЕЛЬНО указывай category — она определяет цвет в календаре. "
                    "Если событие в конкретном месте — заполни location (адрес/название)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start_iso": {"type": "string", "description": "ISO datetime"},
                        "end_iso": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {
                            "type": "string",
                            "description": (
                                "Место/адрес. Для прививок/визитов к педиатру → "
                                "'Городская детская поликлиника №5, ул. Евгения Танцюры, 80, Одесса'. "
                                "Для магазинов/аптек — название и адрес если знаешь."
                            ),
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "baby_food", "baby_medical", "baby_milestone",
                                "personal_eugene", "personal_marina",
                                "critical", "family", "household", "work", "other",
                            ],
                            "description": (
                                "Категория → цвет в Google Calendar:\n"
                                "  baby_food (жёлтый) — прикорм, кормления Матвея\n"
                                "  baby_medical (тёмно-красный) — прививки, врачи Матвея\n"
                                "  baby_milestone (оранжевый) — вехи, первый раз\n"
                                "  personal_eugene (зелёный) — личные напоминания Евгению\n"
                                "  personal_marina (синий) — личные напоминания Марине\n"
                                "  critical (красный) — критически важное\n"
                                "  family (фиолетовый) — общесемейное\n"
                                "  household (серый) — быт, коммуналка\n"
                                "  work (голубой) — рабочее\n"
                                "  other (по умолчанию, без цвета)"
                            ),
                        },
                    },
                    "required": ["title", "category"],
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
            {
                "name": "delete_event",
                "description": "Удалить событие из Google Calendar по его ID. ID бери из find_events / list_upcoming. ВАЖНО: перед удалением переспроси у пользователя «удалить событие X — подтверди?» и удаляй только после явного «да».",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Google Calendar event ID"},
                    },
                    "required": ["event_id"],
                },
            },
            {
                "name": "schedule_vaccine_calendar",
                "description": (
                    "Создать события в Google Calendar для всех предстоящих прививок Матвея "
                    "из его профиля. Используй когда: «составь календарь прививок», "
                    "«запланируй прививки», «график прививок». Все события создаются с категорией "
                    "baby_medical (тёмно-красный) и адресом педиатрической поликлиники."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hour": {"type": "integer", "description": "Час визита (по умолчанию 9)"},
                    },
                },
            },
            {
                "name": "check_event_conflict",
                "description": (
                    "Проверить попадает ли время на типичные часы сна Матвея (для 6-9 мес: "
                    "09:00-10:00 и 13:00-14:30). Используй ПЕРЕД create_event если событие "
                    "касается посещения врача или активности с малышом."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "start_iso": {"type": "string"},
                    },
                    "required": ["start_iso"],
                },
            },
            {
                "name": "add_shopping_item",
                "description": (
                    "Добавить в список покупок. Используй когда пользователь говорит "
                    "«купить X», «нужно купить», «добавь в список». "
                    "Если упомянут конкретный магазин/аптека — заполни place. "
                    "Иначе оставь place пустым (купить где угодно)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string", "description": "Что купить: «сахар», «хлеб», «памперсы»"},
                        "quantity": {"type": "string", "description": "Количество: «1 кг», «2 пачки»"},
                        "place": {
                            "type": "string",
                            "description": "Магазин если уточнён: «АТБ», «Сільпо», «аптека», «маркет». Пусто = где угодно.",
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["item"],
                },
            },
            {
                "name": "list_shopping",
                "description": (
                    "Показать список покупок. Используй когда: «я в АТБ что нужно?», "
                    "«покажи список покупок», «что купить?». Фильтруй по place если "
                    "пользователь сказал что он в конкретном магазине."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "place": {"type": "string", "description": "Фильтр по магазину (опционально)"},
                    },
                },
            },
            {
                "name": "mark_shopping_done",
                "description": "Отметить позицию как купленную. ID берётся из list_shopping.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer"},
                    },
                    "required": ["item_id"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if not self._calendar:
            return {"note": "calendar not configured"}

        if tool_name == "create_event":
            from src.utils.family import PEDIATRICS
            start = None
            if tool_input.get("start_iso"):
                try:
                    start = datetime.fromisoformat(tool_input["start_iso"])
                except ValueError:
                    pass
            if not start:
                from src.utils.time import now_kyiv
                start = now_kyiv()

            # Category → Google Calendar colorId
            color_map = {
                "baby_food": "5",        # Banana (yellow)
                "baby_medical": "11",    # Tomato (dark red)
                "baby_milestone": "6",   # Tangerine (orange)
                "personal_eugene": "10", # Basil (green)
                "personal_marina": "9",  # Blueberry (blue)
                "critical": "4",         # Flamingo (red)
                "family": "3",           # Grape (purple)
                "household": "8",        # Graphite (gray)
                "work": "7",             # Peacock (cyan)
                "other": None,
            }
            category = tool_input.get("category", "other")
            color_id = color_map.get(category)

            # Default location for baby_medical → pediatric clinic
            location = tool_input.get("location", "")
            if not location and category == "baby_medical":
                location = f"{PEDIATRICS['clinic']}, {PEDIATRICS['address']}"

            event = await self._calendar.create_event(
                title=tool_input["title"],
                start=start,
                description=tool_input.get("description", ""),
                location=location,
                color_id=color_id,
            )
            return {
                "event_id": event.event_id,
                "title": event.title,
                "category": category,
                "color_id": color_id,
                "location": location,
            }

        elif tool_name == "list_upcoming":
            events = await self._calendar.list_upcoming(days=tool_input.get("days", 7))
            return [{"title": e.title, "start": e.start.isoformat()} for e in events]

        elif tool_name == "find_events":
            events = await self._calendar.find_events(tool_input["query"])
            return [{"title": e.title, "start": e.start.isoformat(), "id": e.event_id} for e in events]

        elif tool_name == "delete_event":
            ok = await self._calendar.delete_event(tool_input["event_id"])
            return {"deleted": ok, "event_id": tool_input["event_id"]}

        elif tool_name == "schedule_vaccine_calendar":
            from src.utils.family import CHILD, PEDIATRICS
            hour = int(tool_input.get("hour", 9))
            created = []
            for vname, vdate in CHILD["vaccines_upcoming"]:
                start = datetime(vdate.year, vdate.month, vdate.day, hour, 0)
                try:
                    event = await self._calendar.create_event(
                        title=f"Прививка: {vname}",
                        start=start,
                        description="Автоматически создано Ежедневником из календаря прививок Матвея.",
                        location=f"{PEDIATRICS['clinic']}, {PEDIATRICS['address']}",
                        color_id="11",  # baby_medical → tomato dark red
                    )
                    created.append({
                        "name": vname,
                        "date": vdate.isoformat(),
                        "event_id": event.event_id,
                    })
                except Exception as e:
                    created.append({"name": vname, "date": vdate.isoformat(), "error": str(e)})
            return {"scheduled": created, "count": len(created)}

        elif tool_name == "check_event_conflict":
            try:
                start = datetime.fromisoformat(tool_input["start_iso"])
            except Exception:
                return {"error": "bad start_iso"}
            h, m = start.hour, start.minute
            mins = h * 60 + m
            # Typical 6-9mo nap windows
            morning = (9 * 60, 10 * 60)
            afternoon = (13 * 60, 14 * 60 + 30)
            conflict = None
            if morning[0] <= mins <= morning[1]:
                conflict = "утренний сон (09:00-10:00)"
            elif afternoon[0] <= mins <= afternoon[1]:
                conflict = "дневной сон (13:00-14:30)"
            return {
                "start_iso": tool_input["start_iso"],
                "conflict": conflict,
                "note": "Сон у Матвея нерегулярный — это ориентир, а не правило",
            }

        elif tool_name == "add_shopping_item":
            from sqlalchemy import insert
            from src.db.models import ShoppingItem
            from src.utils.time import iso_now
            place = (tool_input.get("place") or "").strip() or None
            author = getattr(self, "_current_sender", "") or "user"
            async with self._memory._engine.begin() as conn:
                result = await conn.execute(
                    insert(ShoppingItem).values(
                        item=tool_input.get("item", "").strip(),
                        quantity=tool_input.get("quantity") or None,
                        place=place,
                        added_by=author,
                        added_at=iso_now(),
                        notes=tool_input.get("notes") or None,
                    )
                )
            return {
                "success": True,
                "item": tool_input.get("item"),
                "place": place,
                "id": result.inserted_primary_key[0] if result.inserted_primary_key else None,
            }

        elif tool_name == "list_shopping":
            from sqlalchemy import select
            from src.db.models import ShoppingItem
            place = (tool_input.get("place") or "").strip().lower() or None
            async with self._memory._engine.connect() as conn:
                stmt = select(ShoppingItem).where(ShoppingItem.done_at.is_(None))
                rows = list(await conn.execute(stmt))
            items = []
            for r in rows:
                # Match: place=None means "anywhere", show always; place=specific shows only when filter matches
                if place:
                    if r.place and place not in r.place.lower():
                        continue
                items.append({
                    "id": r.id,
                    "item": r.item,
                    "quantity": r.quantity,
                    "place": r.place,
                    "added_by": r.added_by,
                    "notes": r.notes,
                })
            return {"count": len(items), "place_filter": place, "items": items}

        elif tool_name == "mark_shopping_done":
            from sqlalchemy import update as sql_update
            from src.db.models import ShoppingItem
            from src.utils.time import iso_now
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(ShoppingItem)
                    .where(ShoppingItem.id == tool_input["item_id"])
                    .values(done_at=iso_now())
                )
            return {"success": True, "id": tool_input["item_id"]}

        return await super()._call_tool(tool_name, tool_input)
