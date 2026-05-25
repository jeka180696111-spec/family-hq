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
# Baby diary sheet columns (1-indexed, matching Matveika-bot convention):
#   A=date, B=time, C=kind, D=event, E=amount, F=unit, G=details, H=author
_BABY_COLS = ["date", "time", "kind", "event", "amount", "unit", "details", "author"]

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
        date_str = time.strftime("%Y-%m-%d")
        time_str = time.strftime("%H:%M")
        row_values = [
            date_str,
            time_str,
            kind,
            event,
            str(amount) if amount is not None else "",
            unit or "",
            details,
            author,
        ]

        ws = await self._open_worksheet(self._baby_sheet_id, _BABY_WORKSHEET)

        def _append() -> int:
            ws.append_row(row_values, value_input_option="USER_ENTERED")
            # Return the new last row index
            return len(ws.get_all_values())

        row_index = await self._run_sync(_append)
        data = dict(zip(_BABY_COLS, row_values))

        log.info(
            "baby_diary_appended",
            kind=kind,
            event=event,
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

        for i, row in enumerate(all_values, start=1):
            if not row:
                continue
            # Pad short rows so zip always produces full dicts
            padded = row + [""] * (len(_BABY_COLS) - len(row))
            data = dict(zip(_BABY_COLS, padded))

            # Parse date
            try:
                row_dt = datetime.strptime(
                    f"{data['date']} {data['time']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue  # skip header or malformed rows

            if row_dt < cutoff:
                continue

            if kind is not None and data.get("kind") != kind:
                continue

            # Tag rows that were written by Matveika-bot (not us)
            source = (
                data.get("author", "")
                if data.get("author", "") != "family_hq"
                else "family_hq:nanny"
            )

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
            ws.append_row(row_values, value_input_option="USER_ENTERED")
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
