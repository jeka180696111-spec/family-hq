"""Google Sheets integration for Matveika-bot baby diary and family finances sheets."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column layouts ----------------------------------------------------------------
# Baby diary sheet (matching the actual Matveika sheet):
#   A=№ (auto-incremented), B=Дата DD.MM.YYYY, C=Время HH:MM,
#   D=Категория (emoji + Russian), E=Тип/Детали (event),
#   F=Кол-во (мл) — only for food/medicine amount, else empty,
#   G=Примечания ([Author] + details)
_BABY_COLS = ["num", "date", "time", "kind", "event", "amount", "notes"]

# Categories recognized by the Apps Script dashboard (after emoji strip):
# 'Сон', 'Еда', 'Подгузник', 'Прогулка', 'Поездка'.
# Anything else won't get scored — keep these labels exact.
_KIND_LABELS = {
    "sleep": "😴 Сон",
    "food": "🍼 Еда",
    "diaper": "💧 Подгузник",
    "walk": "🚶 Прогулка",
    "trip": "🚗 Поездка",
    "medicine": "💊 Лекарство",
    "symptom": "🌡️ Симптом",
    "milestone": "⭐ Веха",
    "note": "📝 Заметка",
}

# Event labels (column E) — dashboard strips these prefixes too.
_EVENT_PREFIX = {
    "Уснул": "💤 ",
    "Проснулся": "☀️ ",
    "Грудь Л": "🤱 ",
    "Грудь П": "🤱 ",
    "Смесь": "🍼 ",
    "Мокрый": "💧 ",
    "Какал": "💩 ",
    "Смешанный": "🔄 ",
    "Вышли": "🚶 ",
    "Вернулись": "🏠 ",
    "Поехали": "🚗 ",
    "Приехали": "🏁 ",
}


def _prefix_event(event: str) -> str:
    """Add the standard emoji prefix when the event matches a known label."""
    stripped = (event or "").strip()
    prefix = _EVENT_PREFIX.get(stripped)
    if prefix:
        return prefix + stripped
    return stripped

# Other Matveika worksheets (their actual headers):
#   Заметки    : A=Дата, B=Время, C=Автор, D=Заметка
#   Достижения : A=Дата, B=Возраст, C=Достижение, D=Примечание, E=Автор
#   Рост       : A=Дата, B=Возраст, C=Вес (г), D=Рост (см), E=Примечание
#   Здоровье   : A=№, B=Дата, C=Время, D=Тип, E=Название, F=Значение, G=Примечание
#   Врач       : A=№, B=Дата, C=Тип, D=Название, E=Возраст, F=Следующий, G=Примечание
_NOTES_WORKSHEET = "Заметки"
_MILESTONES_WORKSHEET = "Достижения"
_GROWTH_WORKSHEET = "Рост"
_HEALTH_WORKSHEET = "Здоровье"
_DOCTOR_WORKSHEET = "Врач"

# Emoji prefixes for the "Достижение" column (D in Достижения sheet)
_MILESTONE_PREFIX = {
    "Перевернулся": "🔄 ",
    "Пытается ползать": "🐢 ",
    "Пополз": "🐢 ",
    "Сел": "🪑 ",
    "Сел сам": "🪑 ",
    "Встал": "🧍 ",
    "Пошёл": "🚶 ",
    "Первый зуб": "🦷 ",
    "Первое слово": "🗣️ ",
    "Улыбнулся": "😊 ",
    "Засмеялся": "😄 ",
    "Другое": "▪ ",
}

# Emoji prefixes for the Здоровье «Тип» column (D)
_HEALTH_TYPE_PREFIX = {
    "Лекарство": "💊 ",
    "Симптом": "🤒 ",
    "Рвота": "🤮 ",
    "Сильный плач": "😢 ",
    "Сон беспокойный": "😴 ",
    "Температура": "🌡️ ",
    "Сыпь": "🔴 ",
    "Кашель": "😷 ",
    "Другое": "▪ ",
}

# Emoji prefixes for the Врач «Тип» column (C)
_DOCTOR_TYPE_PREFIX = {
    "Прививка": "💉 ",
    "Осмотр": "🩺 ",
    "Анализ": "🧪 ",
    "УЗИ": "📡 ",
    "Консультация": "💬 ",
    "Другое": "▪ ",
}


def _prefix(value: str, table: dict[str, str]) -> str:
    stripped = (value or "").strip()
    return table.get(stripped, "") + stripped


# Finance sheet columns:
#   A=date, B=amount, C=category, D=description, E=member
_FINANCE_COLS = ["date", "amount", "category", "description", "member"]

_BABY_WORKSHEET = "Дневник"
_FINANCE_WORKSHEET = "Расходы"


class SheetRow(BaseModel):
    """A row from any sheet."""

    row_index: int
    data: dict[str, Any]
    sheet_name: str
    source: str  # 'matveika_bot' | 'family_hq:nanny' | 'family_hq:finance'


class SheetsClient:
    """
    Work with existing Matveika-bot and Finance sheets.

    Each record is tagged with a ``source`` field for traceability.
    All blocking gspread calls are run in a thread executor so the async
    event loop is never blocked.
    """

    def __init__(
        self,
        service_account_info: dict,
        baby_sheet_id: str,
        finance_sheet_id: str,
    ) -> None:
        self._sa_info = service_account_info
        self._baby_sheet_id = baby_sheet_id
        self._finance_sheet_id = finance_sheet_id
        self._gc: gspread.Client | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_client(self) -> gspread.Client:
        """Lazy-init gspread client in a thread executor."""
        if self._gc is not None:
            return self._gc

        def _build() -> gspread.Client:
            creds = Credentials.from_service_account_info(
                self._sa_info, scopes=SCOPES
            )
            return gspread.authorize(creds)

        self._gc = await self._run_sync(_build)
        log.info("sheets_client_initialized")
        return self._gc

    async def _run_sync(self, func, *args, **kwargs):
        """Run a blocking gspread call in the default thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def _open_worksheet(
        self, sheet_id: str, worksheet_name: str
    ) -> gspread.Worksheet:
        gc = await self._get_client()
        spreadsheet = await self._run_sync(gc.open_by_key, sheet_id)
        return await self._run_sync(spreadsheet.worksheet, worksheet_name)

    # ------------------------------------------------------------------
    # Baby diary
    # ------------------------------------------------------------------

    async def append_baby_diary(
        self,
        kind: str,
        event: str,
        time: datetime,
        amount: float | None = None,
        unit: str | None = None,
        details: str = "",
        author: str = "family_hq",
    ) -> SheetRow:
        """
        Append a baby diary record.

        *kind* must be one of: ``sleep``, ``food``, ``medicine``,
        ``note``, ``symptom``, ``milestone``.

        The appended row is tagged with source ``'family_hq:nanny'``.
        """
        date_str = time.strftime("%d.%m.%Y")
        time_str = time.strftime("%H:%M")
        kind_label = _KIND_LABELS.get(kind, kind)
        event_label = _prefix_event(event)
        author_label = f"[{author}]" if author and not author.startswith("[") else (author or "")
        notes_parts = [p for p in (author_label, details) if p]
        notes_str = " ".join(notes_parts)
        amount_str = str(amount) if amount is not None else ""

        ws = await self._open_worksheet(self._baby_sheet_id, _BABY_WORKSHEET)

        def _append() -> tuple[int, int]:
            # Compute next sequential № from column A
            existing = ws.col_values(1)
            next_num = 1
            for val in reversed(existing):
                try:
                    next_num = int(val) + 1
                    break
                except (ValueError, TypeError):
                    continue
            row_values = [
                str(next_num),
                date_str,
                time_str,
                kind_label,
                event_label,
                amount_str,
                notes_str,
            ]
            # Force append starting from column A — otherwise gspread guesses
            # the table range from the last non-empty cell and offsets right.
            ws.append_row(
                row_values,
                value_input_option="USER_ENTERED",
                table_range="A1",
            )
            return len(ws.get_all_values()), next_num

        row_index, next_num = await self._run_sync(_append)
        row_values = [
            str(next_num), date_str, time_str, kind_label, event_label,
            amount_str, notes_str,
        ]
        data = dict(zip(_BABY_COLS, row_values))

        log.info(
            "baby_diary_appended",
            kind=kind,
            entry=event,
            row_index=row_index,
        )
        return SheetRow(
            row_index=row_index,
            data=data,
            sheet_name=_BABY_WORKSHEET,
            source="family_hq:nanny",
        )

    async def get_baby_diary(
        self,
        days: int = 7,
        kind: str | None = None,
    ) -> list[SheetRow]:
        """
        Fetch recent baby diary records.

        Returns rows from the last *days* days, optionally filtered to a
        specific *kind* (e.g. ``'sleep'``).
        """
        ws = await self._open_worksheet(self._baby_sheet_id, _BABY_WORKSHEET)
        all_values: list[list[str]] = await self._run_sync(ws.get_all_values)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results: list[SheetRow] = []

        # Map English kind key from agent → expected Категория label in sheet
        kind_to_label = {
            "sleep": "Сон", "food": "Еда", "diaper": "Подгузник",
            "walk": "Прогулка", "trip": "Поездка",
            "medicine": "Лекарство", "symptom": "Симптом",
            "milestone": "Веха", "note": "Заметка",
        }
        target_label = kind_to_label.get(kind, kind) if kind else None

        for i, row in enumerate(all_values, start=1):
            if not row:
                continue
            # Pad short rows so zip always produces full dicts
            padded = row + [""] * (len(_BABY_COLS) - len(row))
            data = dict(zip(_BABY_COLS, padded))

            # Parse date — sheet uses DD.MM.YYYY HH:MM
            date_str = data.get("date", "").strip()
            time_str = data.get("time", "").strip() or "00:00"
            row_dt = None
            for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
                try:
                    row_dt = datetime.strptime(f"{date_str} {time_str}", fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            if row_dt is None:
                continue  # header or malformed

            if row_dt < cutoff:
                continue

            # kind cell contains emoji + Russian label ("😴 Сон"); strip emoji to compare
            if target_label is not None:
                cell_kind = data.get("kind", "")
                # Drop leading non-letter chars (emoji + spaces)
                cleaned = cell_kind
                for ch in cell_kind:
                    if ch.isalpha():
                        break
                    cleaned = cleaned[1:]
                cleaned = cleaned.strip()
                if cleaned != target_label:
                    continue

            # Author is in 'notes' column as "[Name]"; treat anything not 'family_hq' as source
            notes = data.get("notes", "")
            source = "family_hq:nanny" if "family_hq" in notes else (notes or "manual")

            results.append(
                SheetRow(
                    row_index=i,
                    data=data,
                    sheet_name=_BABY_WORKSHEET,
                    source=source,
                )
            )

        log.debug(
            "baby_diary_fetched",
            days=days,
            kind=kind,
            returned=len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Notes, Milestones, Growth, Health, Doctor
    # ------------------------------------------------------------------

    async def append_note(
        self,
        text: str,
        time: datetime,
        author: str = "family_hq",
    ) -> dict:
        """Append a row to «Заметки» (A=Дата, B=Время, C=Автор, D=Заметка)."""
        ws = await self._open_worksheet(self._baby_sheet_id, _NOTES_WORKSHEET)
        row_values = [
            time.strftime("%d.%m.%Y"),
            time.strftime("%H:%M"),
            author,
            text,
        ]

        def _append() -> int:
            ws.append_row(row_values, value_input_option="USER_ENTERED", table_range="A1")
            return len(ws.get_all_values())

        row_index = await self._run_sync(_append)
        log.info("note_appended", row=row_index, preview=text[:60])
        return {"row": row_index, "sheet": _NOTES_WORKSHEET}

    async def append_milestone(
        self,
        milestone: str,
        time: datetime,
        details: str = "",
        author: str = "family_hq",
    ) -> dict:
        """Append to «Достижения» (A=Дата, B=Возраст, C=Достижение, D=Примечание, E=Автор)."""
        from src.utils.baby import matvey_age_short
        ws = await self._open_worksheet(self._baby_sheet_id, _MILESTONES_WORKSHEET)
        milestone_label = _prefix(milestone, _MILESTONE_PREFIX) or f"▪ {milestone}"
        row_values = [
            time.strftime("%d.%m.%Y"),
            matvey_age_short(time.date()),
            milestone_label,
            details,
            author,
        ]

        def _append() -> int:
            ws.append_row(row_values, value_input_option="USER_ENTERED", table_range="A1")
            return len(ws.get_all_values())

        row_index = await self._run_sync(_append)
        log.info("milestone_appended", row=row_index, milestone=milestone)
        return {"row": row_index, "sheet": _MILESTONES_WORKSHEET}

    async def append_growth(
        self,
        weight_g: int | None,
        height_cm: float | None,
        time: datetime,
        details: str = "",
    ) -> dict:
        """Append to «Рост» (A=Дата, B=Возраст, C=Вес (г), D=Рост (см), E=Примечание)."""
        from src.utils.baby import matvey_age_short
        ws = await self._open_worksheet(self._baby_sheet_id, _GROWTH_WORKSHEET)
        row_values = [
            time.strftime("%d.%m.%Y"),
            matvey_age_short(time.date()),
            str(weight_g) if weight_g is not None else "",
            str(height_cm) if height_cm is not None else "",
            details,
        ]

        def _append() -> int:
            ws.append_row(row_values, value_input_option="USER_ENTERED", table_range="A1")
            return len(ws.get_all_values())

        row_index = await self._run_sync(_append)
        log.info("growth_appended", row=row_index, weight=weight_g, height=height_cm)
        return {"row": row_index, "sheet": _GROWTH_WORKSHEET}

    async def append_health(
        self,
        type_: str,
        name: str,
        time: datetime,
        value: str = "",
        details: str = "",
    ) -> dict:
        """Append to «Здоровье» (A=№, B=Дата, C=Время, D=Тип, E=Название, F=Значение, G=Примечание)."""
        ws = await self._open_worksheet(self._baby_sheet_id, _HEALTH_WORKSHEET)
        type_label = _prefix(type_, _HEALTH_TYPE_PREFIX) or type_
        # Name in column E often mirrors type emoji; keep it as written (Nanny passes the right thing)
        name_label = name

        def _append() -> tuple[int, int]:
            existing = ws.col_values(1)
            next_num = 1
            for val in reversed(existing):
                try:
                    next_num = int(val) + 1
                    break
                except (ValueError, TypeError):
                    continue
            row_values = [
                str(next_num),
                time.strftime("%d.%m.%Y"),
                time.strftime("%H:%M"),
                type_label,
                name_label,
                value,
                details,
            ]
            ws.append_row(row_values, value_input_option="USER_ENTERED", table_range="A1")
            return len(ws.get_all_values()), next_num

        row_index, next_num = await self._run_sync(_append)
        log.info("health_appended", row=row_index, num=next_num, type=type_, name=name)
        return {"row": row_index, "num": next_num, "sheet": _HEALTH_WORKSHEET}

    async def append_doctor(
        self,
        type_: str,
        name: str,
        time: datetime,
        next_due: str = "",
        details: str = "",
    ) -> dict:
        """Append to «Врач» (A=№, B=Дата, C=Тип, D=Название, E=Возраст, F=Следующий, G=Примечание)."""
        from src.utils.baby import matvey_age_short
        ws = await self._open_worksheet(self._baby_sheet_id, _DOCTOR_WORKSHEET)
        type_label = _prefix(type_, _DOCTOR_TYPE_PREFIX) or type_

        def _append() -> tuple[int, int]:
            existing = ws.col_values(1)
            next_num = 1
            for val in reversed(existing):
                try:
                    next_num = int(val) + 1
                    break
                except (ValueError, TypeError):
                    continue
            row_values = [
                str(next_num),
                time.strftime("%d.%m.%Y"),
                type_label,
                name,
                matvey_age_short(time.date()),
                next_due,
                details,
            ]
            ws.append_row(row_values, value_input_option="USER_ENTERED", table_range="A1")
            return len(ws.get_all_values()), next_num

        row_index, next_num = await self._run_sync(_append)
        log.info("doctor_appended", row=row_index, num=next_num, type=type_, name=name)
        return {"row": row_index, "num": next_num, "sheet": _DOCTOR_WORKSHEET}

    # ------------------------------------------------------------------
    # Finances
    # ------------------------------------------------------------------

    async def append_expense(
        self,
        amount: float,
        category: str,
        description: str,
        date: datetime,
        member: str = "Я",
    ) -> SheetRow:
        """
        Append a finance record.

        *member* is typically ``'Я'``, ``'Жена'``, or ``'Малыш'``.
        The appended row is tagged with source ``'family_hq:finance'``.
        """
        date_str = date.strftime("%Y-%m-%d")
        row_values = [date_str, str(amount), category, description, member]

        ws = await self._open_worksheet(self._finance_sheet_id, _FINANCE_WORKSHEET)

        def _append() -> int:
            ws.append_row(
                row_values,
                value_input_option="USER_ENTERED",
                table_range="A1",
            )
            return len(ws.get_all_values())

        row_index = await self._run_sync(_append)
        data = dict(zip(_FINANCE_COLS, row_values))

        log.info(
            "expense_appended",
            amount=amount,
            category=category,
            row_index=row_index,
        )
        return SheetRow(
            row_index=row_index,
            data=data,
            sheet_name=_FINANCE_WORKSHEET,
            source="family_hq:finance",
        )

    async def get_expenses(
        self,
        days: int = 30,
        category: str | None = None,
    ) -> list[SheetRow]:
        """
        Fetch recent expense records.

        Returns rows from the last *days* days, optionally filtered to a
        specific *category*.
        """
        ws = await self._open_worksheet(self._finance_sheet_id, _FINANCE_WORKSHEET)
        all_values: list[list[str]] = await self._run_sync(ws.get_all_values)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results: list[SheetRow] = []

        for i, row in enumerate(all_values, start=1):
            if not row:
                continue
            padded = row + [""] * (len(_FINANCE_COLS) - len(row))
            data = dict(zip(_FINANCE_COLS, padded))

            try:
                row_dt = datetime.strptime(data["date"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            if row_dt < cutoff:
                continue

            if category is not None and data.get("category") != category:
                continue

            results.append(
                SheetRow(
                    row_index=i,
                    data=data,
                    sheet_name=_FINANCE_WORKSHEET,
                    source="family_hq:finance",
                )
            )

        log.debug(
            "expenses_fetched",
            days=days,
            category=category,
            returned=len(results),
        )
        return results

    async def get_monthly_budget_summary(
        self, year: int, month: int
    ) -> dict[str, float]:
        """
        Return category totals for a given month.

        The returned dict maps category name → total amount (float).
        """
        ws = await self._open_worksheet(self._finance_sheet_id, _FINANCE_WORKSHEET)
        all_values: list[list[str]] = await self._run_sync(ws.get_all_values)

        prefix = f"{year}-{month:02d}-"
        totals: dict[str, float] = {}

        for row in all_values:
            if not row:
                continue
            padded = row + [""] * (len(_FINANCE_COLS) - len(row))
            data = dict(zip(_FINANCE_COLS, padded))

            if not data["date"].startswith(prefix):
                continue

            cat = data.get("category", "Прочее") or "Прочее"
            try:
                amt = float(data.get("amount", 0) or 0)
            except ValueError:
                continue

            totals[cat] = totals.get(cat, 0.0) + amt

        log.debug(
            "monthly_budget_summary_computed",
            year=year,
            month=month,
            categories=len(totals),
        )
        return totals
