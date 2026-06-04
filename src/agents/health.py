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

    def __init__(self, *args, sheets_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sheets = sheets_client

    def get_system_prompt(self) -> str:
        from src.prompts.health import get_health_prompt
        return get_health_prompt(family_members=[])

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "prepare_doctor_visit",
                "description": (
                    "Собрать чек-лист перед визитом к врачу. "
                    "Используй когда: «завтра к педиатру», «на прием в среду», «иду к врачу», "
                    "«что взять к Панковой». Просканирует Здоровье/Врач/Симптомы за последние N дней "
                    "и составит список: что записать, какие вопросы задать, что показать."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {
                            "type": "string",
                            "enum": ["matvey", "eugene", "marina"],
                            "description": "Кто идёт к врачу",
                        },
                        "days_back": {
                            "type": "integer",
                            "description": "За сколько дней собрать данные (по умолчанию 30)",
                        },
                        "doctor_kind": {
                            "type": "string",
                            "description": "Тип врача: педиатр, фтизиатр, терапевт, узи (опционально, для фокусировки)",
                        },
                    },
                    "required": ["member"],
                },
            },
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

        if tool_name == "prepare_doctor_visit":
            return await self._prepare_doctor_visit(tool_input)

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

    async def _prepare_doctor_visit(self, tool_input: dict[str, Any]) -> dict:
        """Aggregate recent health/vaccine/symptom data into a doctor-visit checklist."""
        from datetime import timedelta
        from src.utils.time import now_kyiv
        from src.utils.family import CHILD, FATHER, MOTHER, PEDIATRICS

        member = tool_input.get("member", "matvey")
        days_back = int(tool_input.get("days_back", 30))
        doctor_kind = (tool_input.get("doctor_kind") or "").lower()
        cutoff = now_kyiv() - timedelta(days=days_back)

        # 1) Pull from Google Sheets (Здоровье + Врач + Дневник symptoms)
        sheets_data: dict[str, list] = {"Здоровье": [], "Врач": [], "Дневник_симптомы": []}
        if self._sheets:
            from src.integrations.history_search import _search_sheet
            try:
                # Use broad query to fetch all recent entries — search by member name
                name_filter = ""
                if member == "matvey":
                    name_filter = "матв"
                elif member == "eugene":
                    name_filter = "евген"
                elif member == "marina":
                    name_filter = "марин"

                # Health sheet covers Matvey by design — pull all recent
                if member == "matvey":
                    sheets_data["Здоровье"] = await _search_sheet(self._sheets, "Здоровье", "", cutoff, 50)
                    sheets_data["Врач"] = await _search_sheet(self._sheets, "Врач", "", cutoff, 30)
                    sheets_data["Дневник_симптомы"] = await _search_sheet(self._sheets, "Дневник", "симптом", cutoff, 30)
                else:
                    # Adults — search Здоровье for their name
                    sheets_data["Здоровье"] = await _search_sheet(self._sheets, "Здоровье", name_filter, cutoff, 30)
            except Exception:
                log.exception("checklist_sheet_fetch_failed")

        # 2) Pull HealthRecord rows from SQLite
        from sqlalchemy import select
        from src.db.models import HealthRecord
        async with self._memory._engine.connect() as conn:
            recs = list(await conn.execute(
                select(HealthRecord)
                .where(HealthRecord.member_id == member)
                .where(HealthRecord.date >= cutoff.isoformat())
                .order_by(HealthRecord.date.desc())
                .limit(50)
            ))
        db_records = [
            {"kind": r.kind, "description": r.description, "value": r.value, "date": r.date}
            for r in recs
        ]

        # 3) Profile context
        if member == "matvey":
            profile = {
                "name": CHILD["full_name"],
                "age": "6 мес 1 дн" if days_back else "",
                "weight_g": CHILD["weight_g"],
                "height_cm": CHILD["height_cm"],
                "feeding": CHILD["feeding"],
                "introduced_foods": CHILD["introduced_foods"],
                "allergies": CHILD["allergies"] or "нет",
                "vaccines_done": CHILD["vaccines_done"],
                "vaccines_upcoming": [(n, dt.isoformat()) for n, dt in CHILD["vaccines_upcoming"]],
            }
        elif member == "eugene":
            profile = {
                "name": FATHER["full_name"],
                "weight_kg": FATHER["weight_kg"],
                "blood_type": FATHER["blood_type"],
                "allergies": FATHER["allergies"] or "нет",
                "history": FATHER["medical_history"],
            }
        else:
            profile = {
                "name": MOTHER["full_name"],
                "weight_kg": MOTHER["weight_kg"],
                "blood_type": MOTHER["blood_type"],
                "lactating": MOTHER.get("lactating"),
                "allergies": MOTHER["allergies"] or "нет",
                "history": MOTHER["medical_history"],
            }

        # 4) Compose checklist via Claude
        import json
        context_payload = {
            "patient": profile,
            "doctor_kind": doctor_kind or "не указан",
            "days_back": days_back,
            "from_sheets": sheets_data,
            "from_db": db_records,
            "clinic": f"{PEDIATRICS['clinic']}, {PEDIATRICS['address']}" if member == "matvey" else "",
        }
        prompt = (
            "На основе данных ниже составь короткий ЧЕК-ЛИСТ перед визитом к врачу. "
            "Формат: 3 секции по 3-6 пунктов каждая.\n"
            "  1. Рассказать врачу (свежие симптомы, события, что изменилось)\n"
            "  2. Спросить (вопросы по препаратам/симптомам/развитию)\n"
            "  3. Взять с собой (карточка прививок, последние анализы, направления, текущие лекарства)\n"
            "Без воды. Если данных мало — пиши «по данным мало, спроси что важно для специалиста».\n\n"
            f"ДАННЫЕ:\n{json.dumps(context_payload, ensure_ascii=False, default=str)[:6000]}"
        )
        try:
            response = await self._claude.complete(
                model=self._get_model(),
                system="Ты — медицинский ассистент. Отвечай кратко, по делу.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=900,
            )
            return {
                "patient": profile.get("name"),
                "doctor_kind": doctor_kind,
                "days_back": days_back,
                "data_points": {
                    "sheets_health_rows": len(sheets_data.get("Здоровье", [])),
                    "sheets_doctor_rows": len(sheets_data.get("Врач", [])),
                    "sheets_symptom_rows": len(sheets_data.get("Дневник_симптомы", [])),
                    "db_records": len(db_records),
                },
                "checklist": (response or "").strip(),
            }
        except Exception as e:
            log.exception("checklist_llm_failed")
            return {"error": str(e)}
